import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCircle2,
  CircleDot,
  GitCompareArrows,
  History,
  LoaderCircle,
  Settings2,
  XCircle,
} from "lucide-react";
import { getConfigRegistry } from "../config/config-api";
import { acceptProposal, getRunParameterProposals } from "../../data/parameter-proposals/api";
import type { ParameterProposal } from "../../data/parameter-proposals/types";
import { errorMessage, formatDateTime, shorten } from "../../lib/presentation";
import { useConfirmationDialog } from "../../ui/ConfirmationDialog";
import { classes, countBadge, detailCard } from "../../ui/styles";

export function RunProposals({ runId }: { runId: string }) {
  const queryClient = useQueryClient();
  const [actor, setActor] = useState("local-operator");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [defaultedProposalId, setDefaultedProposalId] = useState<string>();
  const { requestConfirmation, confirmationDialog } = useConfirmationDialog();

  const proposalsQuery = useQuery({
    queryKey: ["parameter-proposals", runId],
    queryFn: ({ signal }) => getRunParameterProposals(runId, signal),
  });
  const configQuery = useQuery({
    queryKey: ["config", "registry"],
    queryFn: ({ signal }) => getConfigRegistry(signal),
    enabled: (proposalsQuery.data?.items.length ?? 0) > 0,
  });
  const generation = configQuery.data?.activation?.generation ?? 0;

  const acceptMutation = useMutation({
    mutationFn: ({ proposal, note }: { proposal: ParameterProposal; note: string }) =>
      acceptProposal({
        runId,
        proposalId: proposal.id,
        actor: actor.trim(),
        expectedGeneration: generation,
        note,
      }),
    onSuccess: async (_, input) => {
      setDefaultedProposalId(input.proposal.id);
      setNotes((current) => ({ ...current, [input.proposal.id]: "" }));
      await Promise.all([
        invalidateProposalConsumers(queryClient, runId),
        queryClient.invalidateQueries({ queryKey: ["config"] }),
      ]);
    },
  });

  const setDefault = (proposal: ParameterProposal) => {
    requestConfirmation({
      title: "Accept this proposal as the default?",
      description: `Accept proposal ${proposal.id} and set its configuration as the default.`,
      confirmLabel: "Accept as default",
      onConfirm: () =>
        acceptMutation.mutate({
          proposal,
          note: notes[proposal.id]?.trim() ?? "",
        }),
    });
  };

  return (
    <article
      className={classes(
        detailCard,
        "col-span-full overflow-hidden p-0 max-[680px]:col-auto max-[680px]:row-auto",
      )}
    >
      <header className="grid grid-cols-[30px_minmax(0,1fr)_auto_auto] items-center gap-2.5 border-b border-line px-[17px] py-4 max-[680px]:grid-cols-[30px_minmax(0,1fr)_auto]">
        <span
          className="grid size-[30px] place-items-center rounded-[8px] border border-line bg-panel text-accent"
          aria-hidden="true"
        >
          <GitCompareArrows size={17} />
        </span>
        <div>
          <h3 className="m-0 text-[0.78rem]">Parameter proposals</h3>
          <p className="mt-[3px] mb-0 text-[0.59rem] text-text-dim">
            Review run-scoped changes and keep an approved result as the default when ready.
          </p>
        </div>
        <label className="flex min-h-8 items-center gap-[7px] rounded-[8px] border border-line bg-bg px-[9px] text-[0.56rem] font-extrabold tracking-[0.06em] text-text-dim uppercase focus-within:border-[rgb(128_163_207_/_45%)] max-[680px]:col-span-full">
          <span>Actor</span>
          <input
            className="w-[115px] min-w-0 border-0 bg-transparent p-0 text-[0.66rem] text-text normal-case outline-0 max-[680px]:w-full"
            value={actor}
            onChange={(event) => setActor(event.target.value)}
            autoComplete="name"
          />
        </label>
        <span className={countBadge}>{proposalsQuery.data?.items.length ?? 0}</span>
      </header>

      {proposalsQuery.isPending ? (
        <ProposalMessage
          icon={<LoaderCircle className="animate-spin" />}
          title="Reading proposals"
          detail="Loading parameter changes and their operator approvals."
        />
      ) : proposalsQuery.isError ? (
        <ProposalMessage
          icon={<XCircle />}
          title="Proposals unavailable"
          detail={errorMessage(proposalsQuery.error)}
          warning
        />
      ) : proposalsQuery.data.items.length === 0 ? (
        <ProposalMessage
          icon={<CircleDot />}
          title="No parameter proposals"
          detail="Analysis-generated changes for this run will appear here."
        />
      ) : (
        <div className="grid gap-2.5 p-3">
          {proposalsQuery.data.items.map((proposal) => {
            const note = notes[proposal.id] ?? "";
            const activating =
              acceptMutation.isPending && acceptMutation.variables?.proposal.id === proposal.id;
            const canSetDefault = !configQuery.isPending && !configQuery.isError;
            const proposalError =
              acceptMutation.error && acceptMutation.variables?.proposal.id === proposal.id
                ? acceptMutation.error
                : undefined;
            return (
              <section
                className="overflow-hidden rounded-[10px] border border-line bg-[rgb(6_10_14_/_32%)]"
                key={proposal.id}
              >
                <header className="grid grid-cols-[minmax(0,1fr)_auto] gap-3.5 px-3.5 py-[13px] max-[680px]:grid-cols-[minmax(0,1fr)]">
                  <div>
                    <span
                      data-testid="proposal-state"
                      className={classes(
                        "mb-[7px] inline-flex min-h-5 items-center rounded-full border px-[7px] text-[0.54rem] font-extrabold tracking-[0.05em] uppercase",
                        proposal.approval
                          ? "border-[rgb(128_163_207_/_25%)] bg-accent-soft text-accent"
                          : "border-line bg-yellow-soft text-yellow",
                      )}
                    >
                      {proposal.approval ? "Approved" : "Awaiting approval"}
                    </span>
                    <h4 className="m-0 overflow-hidden font-mono text-[0.72rem] text-ellipsis whitespace-nowrap">
                      {proposal.id}
                    </h4>
                    <p className="mt-[5px] mb-0 text-[0.66rem] leading-[1.45] text-text-soft">
                      {proposal.reason}
                    </p>
                  </div>
                  <div className="grid content-start justify-items-end gap-[5px] text-[0.57rem] text-text-dim max-[680px]:grid-cols-[auto_minmax(0,1fr)] max-[680px]:justify-items-start">
                    {proposal.confidence !== undefined && (
                      <span>{Math.round(proposal.confidence * 100)}% confidence</span>
                    )}
                    <code
                      className="max-w-[190px] overflow-hidden text-ellipsis whitespace-nowrap"
                      title={proposal.baseContentHash}
                    >
                      Base {shorten(proposal.baseConfigId, 18)}
                    </code>
                  </div>
                </header>

                <ProposalDiff proposal={proposal} />
                <ProposalApproval proposal={proposal} />

                <div className="grid grid-cols-[minmax(190px,1fr)_auto] items-end gap-[7px] px-3.5 pt-3 pb-3.5 max-[680px]:grid-cols-[minmax(0,1fr)]">
                  <label className="grid gap-[5px]">
                    <span className="text-[0.54rem] font-extrabold tracking-[0.06em] text-text-dim uppercase">
                      Review note
                    </span>
                    <input
                      className="min-h-8 w-full rounded-[7px] border border-line bg-bg px-[9px] text-[0.65rem] text-text outline-0 focus:border-[rgb(128_163_207_/_45%)]"
                      value={note}
                      onChange={(event) =>
                        setNotes((current) => ({
                          ...current,
                          [proposal.id]: event.target.value,
                        }))
                      }
                      placeholder="Evidence or rationale"
                    />
                  </label>
                  <button
                    className={proposalActionButton}
                    type="button"
                    disabled={
                      !canSetDefault ||
                      activating ||
                      !actor.trim() ||
                      defaultedProposalId === proposal.id
                    }
                    title={
                      configQuery.isError ? "The default configuration is unavailable." : undefined
                    }
                    onClick={() => setDefault(proposal)}
                  >
                    {activating ? (
                      <LoaderCircle className="animate-spin" size={14} />
                    ) : defaultedProposalId === proposal.id ? (
                      <CheckCircle2 size={14} />
                    ) : (
                      <Settings2 size={14} />
                    )}
                    {defaultedProposalId === proposal.id ? "Default set" : "Accept as default"}
                  </button>
                </div>
                {proposalError ? (
                  <p className="mx-3.5 mt-[-4px] mb-3.5 text-[0.62rem] text-red" role="status">
                    {errorMessage(proposalError)}
                  </p>
                ) : null}
              </section>
            );
          })}
        </div>
      )}
      {confirmationDialog}
    </article>
  );
}

function ProposalDiff({ proposal }: { proposal: ParameterProposal }) {
  return (
    <div
      className="mx-3.5 overflow-hidden rounded-[9px] border border-line bg-panel-soft max-[680px]:overflow-x-auto"
      role="table"
    >
      <div
        className="grid grid-cols-[minmax(130px,0.8fr)_minmax(130px,1fr)_22px_minmax(130px,1fr)] items-center gap-2 border-b border-line bg-panel px-[11px] py-[9px] text-[0.54rem] font-extrabold tracking-[0.07em] text-text-dim uppercase max-[680px]:min-w-[650px]"
        role="row"
      >
        <span role="columnheader">Parameter</span>
        <span role="columnheader">Before</span>
        <span aria-hidden="true" />
        <span role="columnheader">Proposed</span>
      </div>
      {proposal.deltas.map((delta) => (
        <div
          className="grid grid-cols-[minmax(130px,0.8fr)_minmax(130px,1fr)_22px_minmax(130px,1fr)] items-center gap-2 border-b border-line px-[11px] py-[9px] last:border-b-0 max-[680px]:min-w-[650px] [&>svg]:text-text-dim"
          role="row"
          key={delta.parameterId}
        >
          <code
            className="overflow-hidden text-[0.61rem] text-ellipsis whitespace-nowrap text-text-soft"
            role="cell"
          >
            {delta.parameterId}
          </code>
          <span
            className="rounded-md bg-[rgb(255_140_136_/_6%)] px-2 py-[7px] font-mono text-[0.61rem] text-[#c7a6a4] [overflow-wrap:anywhere]"
            role="cell"
          >
            {formatParameterValue(delta.before)}
          </span>
          <ArrowRight size={14} aria-hidden="true" />
          <span
            className="rounded-md bg-accent-soft px-2 py-[7px] font-mono text-[0.61rem] text-accent [overflow-wrap:anywhere]"
            role="cell"
          >
            {formatParameterValue(delta.after)}
          </span>
        </div>
      ))}
    </div>
  );
}

function ProposalApproval({ proposal }: { proposal: ParameterProposal }) {
  const approval = proposal.approval;
  if (!approval) return null;
  return (
    <div className="mx-3.5 mt-3 grid grid-cols-[120px_minmax(0,1fr)] gap-2.5 rounded-[8px] border border-line bg-panel-soft p-2.5 max-[680px]:grid-cols-[minmax(0,1fr)]">
      <div className="flex items-center gap-1.5 text-[0.58rem] font-[750] text-text-dim">
        <History size={14} aria-hidden="true" />
        <span>Operator approval</span>
      </div>
      <ol className="m-0 grid list-none gap-1.5 p-0">
        <li className="grid grid-cols-[7px_auto_minmax(0,1fr)_auto] items-baseline gap-[7px] text-[0.58rem] text-text-dim">
          <span className="size-[7px] rounded-full bg-accent" />
          <strong className="text-[0.6rem] text-text-soft">Approved</strong>
          <span>by {approval.actor}</span>
          {approval.note && (
            <p className="col-[2/-1] m-0 leading-[1.45] text-text-soft">{approval.note}</p>
          )}
          {approval.approvedAt && (
            <time className="text-[0.54rem]" dateTime={approval.approvedAt}>
              {formatDateTime(approval.approvedAt)}
            </time>
          )}
        </li>
      </ol>
    </div>
  );
}

function ProposalMessage({
  icon,
  title,
  detail,
  warning = false,
}: {
  icon: ReactNode;
  title: string;
  detail: string;
  warning?: boolean;
}) {
  return (
    <div className="flex min-h-[100px] items-center gap-[11px] p-5 text-text-dim">
      <span
        className={classes(
          "grid size-[34px] flex-none place-items-center rounded-[9px] [&>svg]:w-[17px]",
          warning ? "bg-red-soft text-red" : "bg-accent-soft text-accent",
        )}
        aria-hidden="true"
      >
        {icon}
      </span>
      <div>
        <strong className="text-[0.7rem] text-text-soft">{title}</strong>
        <p className="mt-1 mb-0 text-[0.62rem] leading-normal">{detail}</p>
      </div>
    </div>
  );
}

const proposalActionButton =
  "inline-flex min-h-8 cursor-pointer items-center justify-center gap-1.5 rounded-[7px] border border-accent bg-accent px-2.5 text-[0.62rem] font-[750] text-bg hover:not-disabled:bg-[#9ff4ec] disabled:cursor-not-allowed disabled:opacity-42";

async function invalidateProposalConsumers(queryClient: QueryClient, runId: string) {
  await Promise.all([
    queryClient.invalidateQueries({
      queryKey: ["parameter-proposals", runId],
    }),
    queryClient.invalidateQueries({ queryKey: ["events"] }),
    queryClient.invalidateQueries({ queryKey: ["run", runId] }),
    queryClient.invalidateQueries({ queryKey: ["runs"] }),
  ]);
}

function formatParameterValue(value: unknown): string {
  if (value === null) return "null";
  if (value === undefined) return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (typeof value === "object" && !Array.isArray(value)) {
    const object = value as Record<string, unknown>;
    if (
      (typeof object.value === "number" || typeof object.value === "string") &&
      typeof object.unit === "string"
    ) {
      return `${object.value} ${object.unit}`;
    }
  }
  const serialized = JSON.stringify(value);
  if (serialized === undefined) return "—";
  return serialized.length > 80 ? `${serialized.slice(0, 77)}…` : serialized;
}

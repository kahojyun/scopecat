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
    <article className="detail-card run-proposals-card">
      <header className="proposals-heading">
        <span aria-hidden="true">
          <GitCompareArrows size={17} />
        </span>
        <div>
          <h3>Parameter proposals</h3>
          <p>Review run-scoped changes and keep an approved result as the default when ready.</p>
        </div>
        <label className="proposal-reviewer">
          <span>Actor</span>
          <input
            value={actor}
            onChange={(event) => setActor(event.target.value)}
            autoComplete="name"
          />
        </label>
        <span className="count-badge">{proposalsQuery.data?.items.length ?? 0}</span>
      </header>

      {proposalsQuery.isPending ? (
        <ProposalMessage
          icon={<LoaderCircle className="spin" />}
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
        <div className="proposal-list">
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
              <section className="proposal" key={proposal.id}>
                <header>
                  <div>
                    <span
                      className={`proposal-state ${proposal.approval ? "approved" : "pending"}`}
                    >
                      {proposal.approval ? "Approved" : "Awaiting approval"}
                    </span>
                    <h4>{proposal.id}</h4>
                    <p>{proposal.reason}</p>
                  </div>
                  <div className="proposal-meta">
                    {proposal.confidence !== undefined && (
                      <span>{Math.round(proposal.confidence * 100)}% confidence</span>
                    )}
                    <code title={proposal.baseContentHash}>
                      Base {shorten(proposal.baseConfigId, 18)}
                    </code>
                  </div>
                </header>

                <ProposalDiff proposal={proposal} />
                <ProposalApproval proposal={proposal} />

                <div className="proposal-actions">
                  <label>
                    <span>Review note</span>
                    <input
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
                    className="proposal-activate"
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
                      <LoaderCircle className="spin" size={14} />
                    ) : defaultedProposalId === proposal.id ? (
                      <CheckCircle2 size={14} />
                    ) : (
                      <Settings2 size={14} />
                    )}
                    {defaultedProposalId === proposal.id ? "Default set" : "Accept as default"}
                  </button>
                </div>
                {proposalError ? (
                  <p className="proposal-error" role="status">
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
    <div className="proposal-diff" role="table">
      <div className="proposal-diff-header" role="row">
        <span role="columnheader">Parameter</span>
        <span role="columnheader">Before</span>
        <span aria-hidden="true" />
        <span role="columnheader">Proposed</span>
      </div>
      {proposal.deltas.map((delta) => (
        <div className="proposal-diff-row" role="row" key={delta.parameterId}>
          <code role="cell">{delta.parameterId}</code>
          <span className="before-value" role="cell">
            {formatParameterValue(delta.before)}
          </span>
          <ArrowRight size={14} aria-hidden="true" />
          <span className="after-value" role="cell">
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
    <div className="proposal-approval">
      <div>
        <History size={14} aria-hidden="true" />
        <span>Operator approval</span>
      </div>
      <ol>
        <li>
          <span className="approval-dot" />
          <strong>Approved</strong>
          <span>by {approval.actor}</span>
          {approval.note && <p>{approval.note}</p>}
          {approval.approvedAt && (
            <time dateTime={approval.approvedAt}>{formatDateTime(approval.approvedAt)}</time>
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
    <div className={warning ? "proposal-message warning" : "proposal-message"}>
      <span aria-hidden="true">{icon}</span>
      <div>
        <strong>{title}</strong>
        <p>{detail}</p>
      </div>
    </div>
  );
}

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

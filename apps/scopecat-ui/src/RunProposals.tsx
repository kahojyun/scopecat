import { useState, type ReactNode } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
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
import { getConfigRegistry } from "./config-api";
import {
  activateProposalCandidate,
  getRunParameterProposals,
  latestProposalDecision,
  reviewParameterProposal,
} from "./proposal-api";
import type {
  ParameterProposal,
  ProposalReviewDecision,
} from "./proposal-types";

interface ReviewInput {
  proposalId: string;
  decision: ProposalReviewDecision;
  note: string;
}

export function RunProposals({ runId }: { runId: string }) {
  const queryClient = useQueryClient();
  const [reviewer, setReviewer] = useState("local-operator");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [defaultedProposalId, setDefaultedProposalId] = useState<string>();

  const proposalsQuery = useQuery({
    queryKey: ["parameter-proposals", runId],
    queryFn: ({ signal }) => getRunParameterProposals(runId, signal),
  });
  const configQuery = useQuery({
    queryKey: ["config", "registry"],
    queryFn: ({ signal }) => getConfigRegistry(signal),
    enabled: (proposalsQuery.data?.items.length ?? 0) > 0,
  });
  const generation = configQuery.data?.active?.generation ?? 0;

  const reviewMutation = useMutation({
    mutationFn: (input: ReviewInput) =>
      reviewParameterProposal(runId, input.proposalId, {
        reviewer: reviewer.trim(),
        note: input.note,
        decision: input.decision,
      }),
    onSuccess: async (_, input) => {
      setNotes((current) => ({ ...current, [input.proposalId]: "" }));
      await invalidateProposalConsumers(queryClient, runId);
    },
  });
  const acceptMutation = useMutation({
    mutationFn: async ({
      proposal,
      note,
    }: {
      proposal: ParameterProposal;
      note: string;
    }) => {
      if (latestProposalDecision(proposal)?.decision !== "approved") {
        await reviewParameterProposal(runId, proposal.id, {
          reviewer: reviewer.trim(),
          note,
          decision: "approved",
        });
      }
      try {
        await activateProposalCandidate({
          runId,
          proposalIds: [proposal.id],
          registeredBy: reviewer.trim(),
          operator: reviewer.trim(),
          expectedGeneration: generation,
          note,
        });
      } catch (error) {
        throw new Error(
          `The proposal is accepted, but the default was not changed: ${errorMessage(error)}`,
          { cause: error },
        );
      }
    },
    onSuccess: async (_, input) => {
      setDefaultedProposalId(input.proposal.id);
      await Promise.all([
        invalidateProposalConsumers(queryClient, runId),
        queryClient.invalidateQueries({ queryKey: ["config"] }),
      ]);
    },
    onError: async () => {
      await invalidateProposalConsumers(queryClient, runId);
    },
  });

  const review = (
    proposalId: string,
    decision: ProposalReviewDecision,
  ) => {
    const label = decision === "approved" ? "Approve" : "Reject";
    if (
      !window.confirm(
        `${label} parameter proposal ${proposalId}? This appends a durable review decision.`,
      )
    ) {
      return;
    }
    reviewMutation.mutate({
      proposalId,
      decision,
      note: notes[proposalId]?.trim() ?? "",
    });
  };
  const setDefault = (proposal: ParameterProposal) => {
    if (
      !window.confirm(
        `Accept proposal ${proposal.id} and set its configuration as the default?`,
      )
    ) {
      return;
    }
    acceptMutation.mutate({
      proposal,
      note: notes[proposal.id]?.trim() ?? "",
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
          <p>
            Review run-scoped changes and keep an approved result as the
            default when ready.
          </p>
        </div>
        <label className="proposal-reviewer">
          <span>Reviewer</span>
          <input
            value={reviewer}
            onChange={(event) => setReviewer(event.target.value)}
            autoComplete="name"
          />
        </label>
        <span className="count-badge">
          {proposalsQuery.data?.items.length ?? 0}
        </span>
      </header>

      {proposalsQuery.isPending ? (
        <ProposalMessage
          icon={<LoaderCircle className="spin" />}
          title="Reading proposals"
          detail="Loading parameter changes and durable review decisions."
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
            const latest = latestProposalDecision(proposal);
            const note = notes[proposal.id] ?? "";
            const reviewing =
              reviewMutation.isPending &&
              reviewMutation.variables?.proposalId === proposal.id;
            const activating =
              acceptMutation.isPending &&
              acceptMutation.variables?.proposal.id === proposal.id;
            const canSetDefault =
              latest?.decision !== "rejected" &&
              latest?.decision !== "invalidated" &&
              !configQuery.isPending &&
              !configQuery.isError;
            const proposalError =
              acceptMutation.error &&
              acceptMutation.variables?.proposal.id === proposal.id
                ? acceptMutation.error
                : reviewMutation.error &&
                    reviewMutation.variables?.proposalId === proposal.id
                  ? reviewMutation.error
                  : undefined;
            return (
              <section className="proposal" key={proposal.id}>
                <header>
                  <div>
                    <span
                      className={`proposal-state ${latest?.decision ?? "pending"}`}
                    >
                      {latest ? titleCase(latest.decision) : "Awaiting review"}
                    </span>
                    <h4>{proposal.id}</h4>
                    <p>{proposal.reason}</p>
                  </div>
                  <div className="proposal-meta">
                    {proposal.confidence !== undefined && (
                      <span>
                        {Math.round(proposal.confidence * 100)}% confidence
                      </span>
                    )}
                    <code title={proposal.baseContentHash}>
                      Base {shorten(proposal.baseConfigId, 18)}
                    </code>
                  </div>
                </header>

                <ProposalDiff proposal={proposal} />
                <ProposalDecisions proposal={proposal} />

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
                    className="proposal-reject"
                    type="button"
                    disabled={
                      reviewing ||
                      !reviewer.trim() ||
                      latest?.decision === "rejected" ||
                      latest?.decision === "invalidated"
                    }
                    onClick={() => review(proposal.id, "rejected")}
                  >
                    {reviewing &&
                    reviewMutation.variables?.decision === "rejected" ? (
                      <LoaderCircle className="spin" size={14} />
                    ) : (
                      <XCircle size={14} />
                    )}
                    Reject
                  </button>
                  {latest?.decision !== "rejected" &&
                    latest?.decision !== "invalidated" && (
                    <button
                      className="proposal-activate"
                      type="button"
                      disabled={
                        !canSetDefault ||
                        activating ||
                        !reviewer.trim() ||
                        defaultedProposalId === proposal.id
                      }
                      title={
                        configQuery.isError
                          ? "The default configuration is unavailable."
                          : undefined
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
                      {defaultedProposalId === proposal.id
                        ? "Default set"
                        : "Accept as default"}
                    </button>
                  )}
                  {latest?.decision !== "approved" &&
                    latest?.decision !== "invalidated" && (
                      <details className="config-advanced-menu">
                        <summary>Advanced</summary>
                        <div>
                          <button
                            className="proposal-approve"
                            type="button"
                            disabled={reviewing || !reviewer.trim()}
                            onClick={() => review(proposal.id, "approved")}
                          >
                            {reviewing &&
                            reviewMutation.variables?.decision ===
                              "approved" ? (
                              <LoaderCircle className="spin" size={14} />
                            ) : (
                              <CheckCircle2 size={14} />
                            )}
                            Approve only
                          </button>
                          <small>
                            Record approval without changing the default.
                          </small>
                        </div>
                      </details>
                    )}
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

function ProposalDecisions({ proposal }: { proposal: ParameterProposal }) {
  if (proposal.decisions.length === 0) return null;
  return (
    <div className="proposal-decisions">
      <div>
        <History size={14} aria-hidden="true" />
        <span>Review history</span>
      </div>
      <ol>
        {proposal.decisions.map((decision) => (
          <li key={decision.eventId}>
            <span className={`decision-dot ${decision.decision}`} />
            <strong>{titleCase(decision.decision)}</strong>
            <span>by {decision.actor}</span>
            {decision.authorityKind === "automatic_policy" && (
              <span>
                via policy {decision.policyId ?? "unknown"}
                {decision.policyVersion
                  ? `@${decision.policyVersion}`
                  : ""}
              </span>
            )}
            {decision.note && <p>{decision.note}</p>}
            {decision.decidedAt && (
              <time dateTime={decision.decidedAt}>
                {formatDateTime(decision.decidedAt)}
              </time>
            )}
          </li>
        ))}
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

async function invalidateProposalConsumers(
  queryClient: QueryClient,
  runId: string,
) {
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
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return String(value);
  }
  if (typeof value === "object" && !Array.isArray(value)) {
    const object = value as Record<string, unknown>;
    if (
      (typeof object.value === "number" ||
        typeof object.value === "string") &&
      typeof object.unit === "string"
    ) {
      return `${object.value} ${object.unit}`;
    }
  }
  const serialized = JSON.stringify(value);
  if (serialized === undefined) return "—";
  return serialized.length > 80 ? `${serialized.slice(0, 77)}…` : serialized;
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function shorten(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  const edge = Math.max(3, Math.floor((maxLength - 1) / 2));
  return `${value.slice(0, edge)}…${value.slice(-edge)}`;
}

function titleCase(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request failed.";
}

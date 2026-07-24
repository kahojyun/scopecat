import { request } from "./api";
import type {
  ActivateProposalCandidateCommand,
  ParameterProposal,
  ParameterProposalDecision,
  ParameterProposalDelta,
  ReviewProposalCommand,
  RunParameterProposals,
} from "./proposal-types";

export async function getRunParameterProposals(
  runId: string,
  signal?: AbortSignal,
): Promise<RunParameterProposals> {
  const raw = await request(
    `/api/v1/runs/${encodeURIComponent(runId)}/parameter-proposals`,
    signal,
  );
  const envelope = record(raw);
  return {
    runId: string(envelope.run_id) ?? runId,
    items: (array(envelope.items) ?? []).map(normalizeProposalView),
  };
}

export async function reviewParameterProposal(
  runId: string,
  proposalId: string,
  command: ReviewProposalCommand,
): Promise<void> {
  await request(
    `/api/v1/runs/${encodeURIComponent(runId)}/parameter-proposals/${encodeURIComponent(proposalId)}/review`,
    undefined,
    jsonRequest({
      run_id: runId,
      proposal_id: proposalId,
      decision: command.decision,
      reviewer: command.reviewer,
      note: command.note ?? "",
    }),
  );
}

export async function activateProposalCandidate(
  command: ActivateProposalCandidateCommand,
): Promise<void> {
  await request(
    "/api/v1/config-registry/candidates/activate",
    undefined,
    jsonRequest({
      run_id: command.runId,
      proposal_ids: command.proposalIds,
      registered_by: command.registeredBy,
      operator: command.operator,
      expected_generation: command.expectedGeneration,
      note: command.note ?? "",
    }),
  );
}

export function latestProposalDecision(
  proposal: ParameterProposal,
): ParameterProposalDecision | undefined {
  return proposal.decisions.at(-1);
}

function normalizeProposalView(value: unknown): ParameterProposal {
  const view = record(value);
  const proposal = record(view.proposal);
  return {
    id: string(proposal.id) ?? "unidentified-proposal",
    sourceRunId:
      string(proposal.source_run_id) ?? "unidentified-source-run",
    baseConfigId:
      string(proposal.base_config_id) ?? "unidentified-base-config",
    baseContentHash:
      string(proposal.base_config_content_hash) ?? "unreported",
    reason: string(proposal.reason) ?? "No proposal reason was reported.",
    confidence: number(proposal.confidence),
    proposedAt: string(proposal.proposed_at),
    deltas: (array(proposal.deltas) ?? []).map(normalizeDelta),
    decisions: (array(view.decisions) ?? []).map(normalizeDecision),
  };
}

function normalizeDelta(value: unknown): ParameterProposalDelta {
  const source = record(value);
  return {
    parameterId:
      string(source.parameter_id) ?? "unidentified-parameter",
    before: parameterValue(source.before),
    after: parameterValue(source.after),
  };
}

function normalizeDecision(value: unknown): ParameterProposalDecision {
  const source = record(value);
  const decision = string(source.decision);
  return {
    eventId: string(source.event_id) ?? "unidentified-decision",
    decision:
      decision === "approved" || decision === "rejected"
        ? decision
        : "invalidated",
    actor: string(source.actor) ?? "unknown-operator",
    note: string(source.note),
    decidedAt: string(source.decided_at),
  };
}

function parameterValue(value: unknown): unknown {
  const source = record(value);
  if (Object.keys(source).length === 0) return value;
  if ("value" in source) return source.value;
  if ("items" in source) return source.items;
  if ("rows" in source) return source.rows;
  return value;
}

function jsonRequest(body: Record<string, unknown>): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function array(value: unknown): unknown[] | undefined {
  return Array.isArray(value) ? value : undefined;
}

function string(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function number(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

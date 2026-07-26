import { request } from "../../api";
import type { DaemonUiApi } from "../../api-contract";
import type {
  ActivateProposalCandidateCommand,
  ParameterProposal,
  ParameterProposalDecision,
  ParameterProposalDelta,
  ReviewProposalCommand,
  RunParameterProposals,
} from "./types";

type WireProposalView = NonNullable<DaemonUiApi["parameterProposals"]["items"]>[number];
type WireProposalDelta = WireProposalView["proposal"]["deltas"][number];
type WireProposalDecision = NonNullable<WireProposalView["decisions"]>[number];

export async function getRunParameterProposals(
  runId: string,
  signal?: AbortSignal,
): Promise<RunParameterProposals> {
  const response = await request<DaemonUiApi["parameterProposals"]>(
    `/api/v1/runs/${encodeURIComponent(runId)}/parameter-proposals`,
    signal,
  );
  return {
    runId: response.run_id,
    items: (response.items ?? []).map(normalizeProposalView),
  };
}

export async function reviewParameterProposal(
  runId: string,
  proposalId: string,
  command: ReviewProposalCommand,
): Promise<void> {
  const payload: DaemonUiApi["parameterProposalReviewCommand"] = {
    decision: command.decision,
    reviewer: command.reviewer,
    note: command.note ?? "",
  };
  await request<DaemonUiApi["parameterProposalDecision"]>(
    `/api/v1/runs/${encodeURIComponent(runId)}/parameter-proposals/${encodeURIComponent(proposalId)}/review`,
    undefined,
    jsonRequest(payload),
  );
}

export async function activateProposalCandidate(
  command: ActivateProposalCandidateCommand,
): Promise<void> {
  const payload: DaemonUiApi["candidateConfigActivationCommand"] = {
    run_id: command.runId,
    proposal_ids:
      command.proposalIds as DaemonUiApi["candidateConfigActivationCommand"]["proposal_ids"],
    registered_by: command.registeredBy,
    operator: command.operator,
    expected_generation: command.expectedGeneration,
    note: command.note ?? "",
  };
  await request<DaemonUiApi["candidateConfigActivationReceipt"]>(
    "/api/v1/config-registry/candidates/activate",
    undefined,
    jsonRequest(payload),
  );
}

export function latestProposalDecision(
  proposal: ParameterProposal,
): ParameterProposalDecision | undefined {
  return proposal.decisions.at(-1);
}

function normalizeProposalView(source: WireProposalView): ParameterProposal {
  return {
    id: source.proposal.id,
    sourceRunId: source.proposal.source_run_id,
    analysisRecordId: source.proposal.analysis_record_id,
    baseConfigId: source.proposal.base_config_id,
    baseContentHash: source.proposal.base_config_content_hash,
    reason: source.proposal.reason,
    confidence: source.proposal.confidence ?? undefined,
    proposedAt: source.proposal.proposed_at,
    deltas: source.proposal.deltas.map(normalizeDelta),
    decisions: (source.decisions ?? []).map(normalizeDecision),
  };
}

function normalizeDelta(source: WireProposalDelta): ParameterProposalDelta {
  return {
    parameterId: source.parameter_id,
    before: parameterValue(source.before),
    after: parameterValue(source.after),
  };
}

function normalizeDecision(source: WireProposalDecision): ParameterProposalDecision {
  return {
    eventId: source.event_id,
    decision: source.decision,
    actor: source.authority.actor,
    authorityKind: source.authority.kind ?? "human",
    policyId: source.authority.kind === "automatic_policy" ? source.authority.policy_id : undefined,
    policyVersion:
      source.authority.kind === "automatic_policy" ? source.authority.policy_version : undefined,
    note: source.note || undefined,
    decidedAt: source.decided_at,
  };
}

function parameterValue(value: WireProposalDelta["before"]): unknown {
  switch (value.shape) {
    case "scalar":
      return value.value;
    case "series":
      return value.items;
    case "table":
      return value.rows;
    case undefined:
      throw new Error("The daemon returned a proposal value without its shape.");
  }
}

function jsonRequest(body: object): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

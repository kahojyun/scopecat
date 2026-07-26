import { request } from "../../api";
import type { DaemonUiApi } from "../../api-contract";
import type {
  ActivateProposalCandidateCommand,
  ApproveProposalCommand,
  ParameterProposal,
  ParameterProposalApproval,
  ParameterProposalDelta,
  RunParameterProposals,
} from "./types";

type WireProposalView = NonNullable<DaemonUiApi["parameterProposals"]["items"]>[number];
type WireProposalDelta = WireProposalView["proposal"]["deltas"][number];
type WireProposalApproval = NonNullable<WireProposalView["approval"]>;

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

export async function approveParameterProposal(
  runId: string,
  proposalId: string,
  command: ApproveProposalCommand,
): Promise<void> {
  const payload: DaemonUiApi["parameterProposalApprovalCommand"] = {
    actor: command.reviewer,
    note: command.note ?? "",
  };
  await request<DaemonUiApi["parameterProposalApproval"]>(
    `/api/v1/runs/${encodeURIComponent(runId)}/parameter-proposals/${encodeURIComponent(proposalId)}/approval`,
    undefined,
    jsonRequest(payload),
  );
}

export async function activateProposalCandidate(
  command: ActivateProposalCandidateCommand,
): Promise<void> {
  const payload: DaemonUiApi["candidateConfigActivationCommand"] = {
    run_id: command.runId,
    proposal_id: command.proposalId,
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
    approval: source.approval ? normalizeApproval(source.approval) : undefined,
  };
}

function normalizeDelta(source: WireProposalDelta): ParameterProposalDelta {
  return {
    parameterId: source.parameter_id,
    before: parameterValue(source.before),
    after: parameterValue(source.after),
  };
}

function normalizeApproval(source: WireProposalApproval): ParameterProposalApproval {
  return {
    actor: source.actor,
    note: source.note || undefined,
    approvedAt: source.approved_at,
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

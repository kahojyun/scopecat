export type ProposalDecision = "approved" | "rejected";

export interface ParameterProposalDelta {
  parameterId: string;
  before: unknown;
  after: unknown;
}

export interface ParameterProposalDecision {
  eventId: string;
  decision: ProposalDecision;
  actor: string;
  authorityKind: "human" | "automatic_policy";
  policyId?: string;
  policyVersion?: string;
  note?: string;
  decidedAt?: string;
}

export interface ParameterProposal {
  id: string;
  sourceRunId: string;
  analysisRecordId: string;
  baseConfigId: string;
  baseContentHash: string;
  reason: string;
  confidence?: number;
  proposedAt?: string;
  deltas: ParameterProposalDelta[];
  decisions: ParameterProposalDecision[];
}

export interface RunParameterProposals {
  runId: string;
  items: ParameterProposal[];
}

export interface DecideProposalCommand {
  reviewer: string;
  note?: string;
  decision: ProposalDecision;
}

export interface ActivateProposalCandidateCommand {
  runId: string;
  proposalId: string;
  registeredBy: string;
  operator: string;
  expectedGeneration: number;
  note?: string;
}

export type ProposalReviewDecision = "approved" | "rejected";
export type ProposalDecision = ProposalReviewDecision | "invalidated";

export interface ParameterProposalDelta {
  parameterId: string;
  before: unknown;
  after: unknown;
}

export interface ParameterProposalDecision {
  eventId: string;
  decision: ProposalDecision;
  actor: string;
  note?: string;
  decidedAt?: string;
}

export interface ParameterProposal {
  id: string;
  sourceRunId: string;
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

export interface ReviewProposalCommand {
  reviewer: string;
  note?: string;
  decision: ProposalReviewDecision;
}

export interface ActivateProposalCandidateCommand {
  runId: string;
  proposalIds: string[];
  registeredBy: string;
  operator: string;
  expectedGeneration: number;
  note?: string;
}

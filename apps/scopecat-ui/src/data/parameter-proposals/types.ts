export interface ParameterProposalDelta {
  parameterId: string;
  before: unknown;
  after: unknown;
}

export interface ParameterProposalApproval {
  actor: string;
  note?: string;
  approvedAt?: string;
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
  approval?: ParameterProposalApproval;
}

export interface RunParameterProposals {
  runId: string;
  items: ParameterProposal[];
}

export interface ApproveProposalCommand {
  reviewer: string;
  note?: string;
}

export interface ActivateProposalCandidateCommand {
  runId: string;
  proposalId: string;
  registeredBy: string;
  operator: string;
  expectedGeneration: number;
  note?: string;
}

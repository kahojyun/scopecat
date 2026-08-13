import type {
  AnalysisArtifactReference,
  AnalysisDatasetDerivation,
  AnalysisDatasetReference,
  AnalysisExecution,
  AnalysisExecutionOutputReference,
  AnalysisFact,
  AnalysisFigureView,
  AnalysisParameterProposalReference,
  AnalysisRecordInput,
  AnalysisTableView,
  MeasurementDatasetSchema,
  MeasurementRecord,
} from "./api-contract";

export type PresentationRunStatus =
  | "accepted"
  | "running"
  | "attention_required"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface RunResource {
  id: string;
  kind: string;
  status?: string;
}

export interface ContentEntry {
  id: string;
  role: string;
  kind: string;
  label: string;
  detail?: string;
  mediaType?: string;
  filename?: string;
}

export interface RunPlanSummary {
  pointCount?: number;
  initialPointCount: number;
  pointLimit: number;
  coordinateIds: string[];
  recordIds: string[];
}

export interface RunPointPlanProgress {
  initialPointCount: number;
  acceptedPointCount: number;
  pointLimit: number;
  decisionCount: number;
  optimizerAttemptCount: number;
  operatorRequestCount: number;
  closed: boolean;
  stopReason?: string;
}

export interface ProjectRun {
  sequence?: number;
  runId: string;
  experimentId: string;
  displayName?: string;
  tags: string[];
  description?: string;
  status: PresentationRunStatus;
  stateLabel: string;
  createdAt?: string;
  updatedAt?: string;
  configHash?: string;
  attentionReason?: string;
  result?: string;
  certainty?: string;
  progressCompleted?: number;
  pointPlan: RunPointPlanProgress;
  plan: RunPlanSummary;
  resources: RunResource[];
  contents: ContentEntry[];
}

export interface ProjectRunPage {
  items: ProjectRun[];
  nextCursor?: number;
}

export interface ProjectEvent {
  id: number;
  runId?: string;
  kind: string;
  occurredAt?: string;
  payload: Record<string, unknown>;
}

export interface ProjectHealth {
  status: string;
  projectId: string;
  projectName: string;
  projectRoot: string;
  details: Record<string, unknown>;
}

export interface MeasurementPreview {
  items: MeasurementRecord[];
  schema?: MeasurementDatasetSchema;
  truncated?: boolean;
  recordCount?: number;
  durableRecordCount?: number;
  livePointIndex?: number;
}

export interface MeasurementLivePreview {
  active: boolean;
  latest?: MeasurementRecord;
  receivedRecordCount: number;
  durableRecordCount: number;
}

export interface MeasurementSlicePreview {
  items: MeasurementRecord[];
  schema?: MeasurementDatasetSchema;
  selectedPointCount: number;
  truncated: boolean;
}

interface RunAnalysisOutputBase {
  id: string;
  title: string;
  producedBy?: AnalysisExecutionOutputReference;
  derivedFrom?: AnalysisDatasetDerivation;
  metadata: Record<string, unknown>;
}

export type RunAnalysisOutput = RunAnalysisOutputBase &
  (
    | { kind: "fact"; content: AnalysisFact }
    | { kind: "dataset"; content: AnalysisDatasetReference }
    | { kind: "artifact"; content: AnalysisArtifactReference }
    | { kind: "table"; content: AnalysisTableView }
    | { kind: "figure"; content: AnalysisFigureView }
    | { kind: "parameter_change_proposal"; content: AnalysisParameterProposalReference }
  );

export interface RunAnalysis {
  id: string;
  title: string;
  key?: string;
  stepId?: string;
  inputs: AnalysisRecordInput[];
  executions: AnalysisExecution[];
  outputs: RunAnalysisOutput[];
}

export interface RunContentPreview {
  entry: ContentEntry;
  format: "text" | "json";
  content: unknown;
}

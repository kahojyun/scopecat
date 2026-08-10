import type {
  AnalysisArtifactReference,
  AnalysisDatasetReference,
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
  coordinateIds: string[];
  recordIds: string[];
}

export interface RunStageLineage {
  sequenceId: string;
  index: number;
  previousRunId?: string;
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
  stage?: RunStageLineage;
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
  nextOffset?: number;
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
  outputs: RunAnalysisOutput[];
}

export interface RunContentPreview {
  entry: ContentEntry;
  format: "text" | "json";
  content: unknown;
}

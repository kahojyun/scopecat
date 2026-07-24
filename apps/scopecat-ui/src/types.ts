export type RunStatus =
  | "accepted"
  | "running"
  | "attention_required"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "terminal"
  | "unknown";

export interface ResourceClaim {
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

export interface ProjectRun {
  sequence?: number;
  runId: string;
  experimentId: string;
  executionMode: string;
  status: RunStatus;
  stateLabel: string;
  createdAt?: string;
  updatedAt?: string;
  configHash?: string;
  attentionReason?: string;
  result?: string;
  certainty?: string;
  progressCompleted?: number;
  plan: RunPlanSummary;
  resources: ResourceClaim[];
  contents: ContentEntry[];
}

export interface ProjectEvent {
  id: number;
  runId?: string;
  kind: string;
  occurredAt?: string;
  payload: Record<string, unknown>;
}

export interface ExperimentDescriptor {
  id: string;
  version: string;
  title: string;
  description?: string;
  tags: string[];
}

export interface ExperimentCatalog {
  revision?: string;
  experiments: ExperimentDescriptor[];
}

export interface ProjectHealth {
  status: string;
  projectId: string;
  projectName: string;
  projectRoot: string;
  details: Record<string, unknown>;
}

export interface MeasurementPreview {
  items: Array<Record<string, unknown>>;
  nextOffset?: number;
}

export interface RunAnalysisOutput {
  kind: string;
  title: string;
  content: unknown;
}

export interface RunAnalysis {
  id: string;
  title: string;
  key?: string;
  stepId?: string;
  outputs: RunAnalysisOutput[];
}

export interface RunContentPreview {
  entry: ContentEntry;
  format: "text" | "json";
  content: unknown;
}

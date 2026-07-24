import type {
  ControlRun,
  DaemonUiApi,
  DurableEvent,
  RegisteredExperimentDescriptor,
  RunContentEntry,
  RunManifest,
  RunResourceView,
} from "./api-schema";
import type {
  ContentEntry,
  ExperimentCatalog,
  ExperimentDescriptor,
  MeasurementPreview,
  ProjectEvent,
  ProjectHealth,
  ProjectRun,
  ProjectRunPage,
  ResourceClaim,
  RunAnalysis,
  RunContentPreview,
  RunStatus,
} from "./types";

const API = {
  health: "/api/v1/health",
  runs: "/api/v1/runs?limit=100&latest=true",
  events: "/api/v1/events?limit=500&latest=true",
  catalog: "/api/v1/catalog",
} as const;

type CurrentRunStatus = Exclude<RunStatus, "terminal" | "unknown">;
type AdmissionResource = NonNullable<
  ControlRun["admission"]["resource_claims"]
>[number];

interface StoredAdmissionSummary {
  plan?: {
    point_count?: number;
    coordinate_ids?: string[];
    record_ids?: string[];
  };
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request<T = unknown>(
  path: string,
  signal?: AbortSignal,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { Accept: "application/json", ...init?.headers },
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError("The local daemon did not respond.");
  }
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail = typeof body.detail === "string" ? body.detail : undefined;
    } catch {
      // Some intermediaries return an empty or non-JSON error response.
    }
    throw new ApiError(
      detail ??
        `The daemon returned ${response.status} ${response.statusText}.`,
      response.status,
    );
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("The daemon returned an invalid JSON response.");
  }
}

export type AttentionAction = DaemonUiApi["attentionCommand"]["action"];

export async function resolveAttention(
  runId: string,
  action: AttentionAction,
): Promise<void> {
  const command: DaemonUiApi["attentionCommand"] = {
    run_id: runId,
    action,
  };
  await request(`/api/v1/runs/${encodeURIComponent(runId)}/attention`, undefined, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(command),
  });
}

export async function getHealth(signal?: AbortSignal): Promise<ProjectHealth> {
  const response = await request<DaemonUiApi["health"]>(API.health, signal);
  return {
    status: response.status,
    projectId: response.project_id,
    projectName: response.project_name,
    projectRoot: response.project_root,
    details: { ...response },
  };
}

export async function getRuns(signal?: AbortSignal): Promise<ProjectRunPage> {
  return normalizeRunPage(
    await request<DaemonUiApi["runPage"]>(API.runs, signal),
  );
}

export async function getOlderRuns(
  before: number,
  signal?: AbortSignal,
): Promise<ProjectRunPage> {
  return normalizeRunPage(
    await request<DaemonUiApi["runPage"]>(
      `/api/v1/runs?limit=100&before=${before}`,
      signal,
    ),
  );
}

function normalizeRunPage(response: DaemonUiApi["runPage"]): ProjectRunPage {
  return {
    items: response.items.map((run) => normalizeRun(run)).sort(compareRuns),
    previousCursor: response.previous_cursor ?? undefined,
  };
}

export async function getRun(
  runId: string,
  signal?: AbortSignal,
): Promise<ProjectRun> {
  const response = await request<DaemonUiApi["runDetail"]>(
    `/api/v1/runs/${encodeURIComponent(runId)}`,
    signal,
  );
  return normalizeRun(
    response.control,
    response.manifest,
    response.resources ?? [],
  );
}

export async function getMeasurementPreview(
  runId: string,
  offset = 0,
  signal?: AbortSignal,
): Promise<MeasurementPreview> {
  const response = await request<DaemonUiApi["measurements"]>(
    `/api/v1/runs/${encodeURIComponent(runId)}/measurements?limit=100&offset=${offset}`,
    signal,
  );
  return {
    items: (response.items ?? []) as Array<Record<string, unknown>>,
    nextOffset: response.next_offset ?? undefined,
  };
}

export async function getRunAnalyses(
  runId: string,
  signal?: AbortSignal,
): Promise<RunAnalysis[]> {
  const response = await request<DaemonUiApi["runAnalyses"]>(
    `/api/v1/runs/${encodeURIComponent(runId)}/analyses`,
    signal,
  );
  return (response.items ?? []).map(({ entry, analysis }) => ({
    id: entry.id,
    title: analysis.title,
    key: analysis.key ?? undefined,
    stepId: analysis.step_id ?? undefined,
    outputs: analysis.outputs.map((output) => ({
      kind: output.kind,
      title: output.title,
      content: output.content,
    })),
  }));
}

export function canPreviewRunContent(entry: ContentEntry): boolean {
  return (
    entry.role === "record" ||
    (entry.role === "dataset" &&
      ["data_table", "data_array"].includes(entry.kind)) ||
    (entry.role === "artifact" && artifactFormat(entry) !== undefined)
  );
}

export async function getRunContent(
  runId: string,
  entry: ContentEntry,
  signal?: AbortSignal,
): Promise<RunContentPreview> {
  const run = encodeURIComponent(runId);
  const selector = encodeURIComponent(entry.id);
  if (entry.role === "record") {
    const response = await request<DaemonUiApi["recordJson"]>(
      `/api/v1/runs/${run}/records/${selector}/json` +
        `?expected_kind=${encodeURIComponent(entry.kind)}`,
      signal,
    );
    return {
      entry: normalizeContentEntry(response.record, 0),
      format: "json",
      content: response.content,
    };
  }
  if (entry.role === "dataset") {
    const response = await request<DaemonUiApi["datasetContent"]>(
      `/api/v1/runs/${run}/datasets/${selector}`,
      signal,
    );
    return {
      entry: normalizeContentEntry(response.dataset, 0),
      format: "json",
      content: response.content,
    };
  }

  const format = artifactFormat(entry);
  if (!format) {
    throw new ApiError("This artifact does not have a browser-readable format.");
  }
  const path =
    `/api/v1/runs/${run}/artifacts/${selector}/${format}` +
    `?expected_kind=${encodeURIComponent(entry.kind)}`;
  if (format === "text") {
    const response = await request<DaemonUiApi["artifactText"]>(path, signal);
    return {
      entry: normalizeContentEntry(response.artifact, 0),
      format,
      content: response.content,
    };
  }
  const response = await request<DaemonUiApi["artifactJson"]>(path, signal);
  return {
    entry: normalizeContentEntry(response.artifact, 0),
    format,
    content: response.content,
  };
}

export async function getEvents(signal?: AbortSignal): Promise<ProjectEvent[]> {
  return normalizeEvents(
    await request<DaemonUiApi["eventPage"]>(API.events, signal),
  );
}

export async function getRunEvents(
  runId: string,
  signal?: AbortSignal,
): Promise<ProjectEvent[]> {
  return normalizeEvents(
    await request<DaemonUiApi["eventPage"]>(
      `/api/v1/events?limit=500&latest=true&run_id=${encodeURIComponent(runId)}`,
      signal,
    ),
  );
}

function normalizeEvents(response: DaemonUiApi["eventPage"]): ProjectEvent[] {
  return response.items
    .map(normalizeEvent)
    .sort((left, right) => left.id - right.id);
}

export async function getCatalog(
  signal?: AbortSignal,
): Promise<ExperimentCatalog> {
  const response = await request<DaemonUiApi["catalog"]>(API.catalog, signal);
  return {
    revision: response.revision,
    experiments: (response.experiments ?? []).map(normalizeExperiment),
  };
}

function normalizeRun(
  control: ControlRun,
  manifest?: RunManifest,
  detailResources?: RunResourceView[],
): ProjectRun {
  const admission = control.admission;
  const outcome = control.outcome ?? undefined;
  const summary = admission.plan_summary as StoredAdmissionSummary | undefined;
  const plan = summary?.plan;
  const status = normalizeStatus(control);
  return {
    sequence: control.sequence,
    runId: admission.run_id,
    experimentId: admission.experiment_id,
    executionMode: admission.execution_mode,
    status,
    stateLabel: statusLabel(status),
    createdAt: admission.admitted_at,
    updatedAt: control.updated_at,
    configHash: admission.config_content_hash,
    attentionReason: control.attention_reason ?? undefined,
    result: outcome?.result,
    certainty: outcome?.certainty,
    plan: {
      pointCount: plan?.point_count,
      coordinateIds: plan?.coordinate_ids ?? [],
      recordIds: plan?.record_ids ?? [],
    },
    resources:
      detailResources !== undefined
        ? detailResources.map(normalizeRunResource)
        : (admission.resource_claims ?? []).map(normalizeResourceClaim),
    contents: (manifest?.contents ?? []).map(normalizeContentEntry),
  };
}

function normalizeEvent(event: DurableEvent): ProjectEvent {
  return {
    id: event.event_id,
    runId: event.run_id ?? undefined,
    kind: event.kind,
    occurredAt: event.occurred_at,
    payload: event.payload ?? {},
  };
}

function normalizeExperiment(
  experiment: RegisteredExperimentDescriptor,
): ExperimentDescriptor {
  return {
    id: experiment.id,
    version: experiment.version,
    title: experiment.title ?? experiment.id,
    description: experiment.description ?? undefined,
    tags: experiment.tags ?? [],
  };
}

function normalizeResourceClaim(
  resource: AdmissionResource,
): ResourceClaim {
  return {
    id: resource.id,
    kind: resource.kind ?? "instrument",
  };
}

function normalizeRunResource(resource: RunResourceView): ResourceClaim {
  return {
    id: resource.resource.id,
    kind: resource.resource.kind ?? "instrument",
    status: resource.status,
  };
}

function normalizeContentEntry(
  entry: RunContentEntry,
  index: number,
): ContentEntry {
  const mediaType = entry.media_type ?? undefined;
  const filename = entry.filename ?? undefined;
  return {
    id: entry.id,
    role: entry.role,
    kind: entry.kind,
    label:
      entry.title ??
      filename ??
      `${titleCase(entry.role)} ${index + 1}`,
    detail: mediaType ?? entry.kind,
    mediaType,
    filename,
  };
}

function artifactFormat(
  entry: ContentEntry,
): RunContentPreview["format"] | undefined {
  const mediaType = entry.mediaType?.toLocaleLowerCase();
  const filename = entry.filename?.toLocaleLowerCase();
  if (
    mediaType === "application/json" ||
    mediaType?.endsWith("+json") ||
    filename?.endsWith(".json")
  ) {
    return "json";
  }
  if (
    mediaType?.startsWith("text/") ||
    filename?.endsWith(".txt") ||
    filename?.endsWith(".md") ||
    filename?.endsWith(".csv")
  ) {
    return "text";
  }
  return undefined;
}

function normalizeStatus(control: ControlRun): CurrentRunStatus {
  if (control.state !== "terminal") {
    return control.state;
  }
  switch (control.outcome!.result) {
    case "succeeded":
      return "succeeded";
    case "failed":
      return "failed";
    case "cancelled":
      return "cancelled";
  }
}

function statusLabel(status: CurrentRunStatus): string {
  switch (status) {
    case "accepted":
      return "Accepted";
    case "running":
      return "Running";
    case "attention_required":
      return "Needs attention";
    case "succeeded":
      return "Succeeded";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Cancelled";
  }
}

function compareRuns(left: ProjectRun, right: ProjectRun): number {
  if (left.sequence !== undefined && right.sequence !== undefined) {
    return right.sequence - left.sequence;
  }
  return (right.updatedAt ?? "").localeCompare(left.updatedAt ?? "");
}

function titleCase(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

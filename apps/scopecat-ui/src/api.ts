import type {
  DaemonUiApi,
  DurableEvent,
  RunContentEntry,
  RunControlView,
  RunManifest,
  RunResourceView,
} from "./api-contract";
import type {
  ContentEntry,
  MeasurementPreview,
  ProjectEvent,
  ProjectHealth,
  ProjectRun,
  ProjectRunPage,
  PresentationRunStatus,
  RunAnalysis,
  RunContentPreview,
  RunResource,
} from "./types";

const API = {
  health: "/api/v1/health",
  runs: "/api/v1/runs?limit=100",
  events: "/api/v1/events?limit=500&latest=true",
} as const;

type RunResourceRequirement =
  RunControlView["admission"]["plan"]["run_resource_requirements"][number];

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
  const headers = new Headers(init?.headers);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers,
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
      detail ?? `The daemon returned ${response.status} ${response.statusText}.`,
      response.status,
    );
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError("The daemon returned an invalid JSON response.");
  }
}

export async function resolveAttention(runId: string): Promise<void> {
  await request(`/api/v1/runs/${encodeURIComponent(runId)}/attention`, undefined, {
    method: "POST",
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
  return normalizeRunPage(await request<DaemonUiApi["runPage"]>(API.runs, signal));
}

export async function getOlderRuns(before: number, signal?: AbortSignal): Promise<ProjectRunPage> {
  return normalizeRunPage(
    await request<DaemonUiApi["runPage"]>(`/api/v1/runs?limit=100&before=${before}`, signal),
  );
}

function normalizeRunPage(response: DaemonUiApi["runPage"]): ProjectRunPage {
  return {
    items: response.items.map((run) => normalizeRun(run.control, run.manifest)).sort(compareRuns),
    nextCursor: response.next_cursor ?? undefined,
  };
}

export async function getRun(runId: string, signal?: AbortSignal): Promise<ProjectRun> {
  const response = await request<DaemonUiApi["runDetail"]>(
    `/api/v1/runs/${encodeURIComponent(runId)}`,
    signal,
  );
  return normalizeRun(response.control, response.manifest, response.resources ?? []);
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

export async function getRunAnalyses(runId: string, signal?: AbortSignal): Promise<RunAnalysis[]> {
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
      kind: analysisOutputKind(output.kind),
      title: output.title,
      content: output.content,
    })),
  }));
}

function analysisOutputKind(kind: string): RunAnalysis["outputs"][number]["kind"] {
  if (kind === "table" || kind === "figure" || kind === "parameter_change_proposal") {
    return kind;
  }
  throw new ApiError(`The daemon returned an unsupported analysis output kind: ${kind}.`);
}

export function canPreviewRunContent(entry: ContentEntry): boolean {
  return (
    entry.role === "record" || (entry.role === "artifact" && artifactFormat(entry) !== undefined)
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
      entry: normalizeContentEntry(response.dataset_entry, 0),
      format: "json",
      content: response.dataset,
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
  return normalizeEvents(await request<DaemonUiApi["eventPage"]>(API.events, signal));
}

export async function getRunEvents(runId: string, signal?: AbortSignal): Promise<ProjectEvent[]> {
  return normalizeEvents(
    await request<DaemonUiApi["eventPage"]>(
      `/api/v1/events?limit=500&latest=true&run_id=${encodeURIComponent(runId)}`,
      signal,
    ),
  );
}

function normalizeEvents(response: DaemonUiApi["eventPage"]): ProjectEvent[] {
  return response.items.map(normalizeEvent).sort((left, right) => left.id - right.id);
}

function normalizeRun(
  control: RunControlView,
  manifest: RunManifest,
  detailResources?: RunResourceView[],
): ProjectRun {
  const admission = control.admission;
  const outcome = manifest.outcome ?? undefined;
  const plan = admission.plan;
  const status = normalizeStatus(control, manifest);
  return {
    sequence: control.sequence,
    runId: admission.run_id,
    experimentId: plan.experiment_id,
    status,
    stateLabel: statusLabel(status),
    createdAt: admission.admitted_at,
    updatedAt: control.updated_at,
    configHash: manifest.config_content_hash,
    attentionReason: control.attention_reason ?? undefined,
    result: outcome?.result,
    certainty: outcome?.certainty,
    plan: {
      pointCount: plan.point_count,
      coordinateIds: plan.coordinate_ids ?? [],
      recordIds: plan.record_ids ?? [],
    },
    resources:
      detailResources !== undefined
        ? detailResources.map(normalizeRunResource)
        : (plan.run_resource_requirements ?? []).map(normalizeResourceRequirement),
    contents: manifest.contents.map(normalizeContentEntry),
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

function normalizeResourceRequirement(resource: RunResourceRequirement): RunResource {
  return {
    id: resource.id,
    kind: resource.kind ?? "instrument",
  };
}

function normalizeRunResource(resource: RunResourceView): RunResource {
  return {
    id: resource.resource.id,
    kind: resource.resource.kind ?? "instrument",
    status: resource.status,
  };
}

function normalizeContentEntry(entry: RunContentEntry, index: number): ContentEntry {
  const mediaType = entry.media_type ?? undefined;
  const filename = entry.filename ?? undefined;
  return {
    id: entry.id,
    role: entry.role,
    kind: entry.kind,
    label: entry.title ?? filename ?? `${titleCase(entry.role)} ${index + 1}`,
    detail: mediaType ?? entry.kind,
    mediaType,
    filename,
  };
}

function artifactFormat(entry: ContentEntry): RunContentPreview["format"] | undefined {
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

function normalizeStatus(control: RunControlView, manifest: RunManifest): PresentationRunStatus {
  if (control.state === "attention_required") {
    return "attention_required";
  }
  switch (manifest.outcome?.result) {
    case "succeeded":
      return "succeeded";
    case "failed":
      return "failed";
    case "cancelled":
      return "cancelled";
  }
  return control.state === "leased" ? "running" : "accepted";
}

function statusLabel(status: PresentationRunStatus): string {
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
  return value.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

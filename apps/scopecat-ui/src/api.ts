import type {
  ContentEntry,
  ExperimentCatalog,
  ExperimentDescriptor,
  MeasurementPreview,
  ProjectEvent,
  ProjectHealth,
  ProjectRun,
  ResourceClaim,
  RunAnalysis,
  RunContentPreview,
  RunStatus,
} from "./types";

const API = {
  health: "/api/v1/health",
  runs: "/api/v1/runs?limit=500&latest=true",
  events: "/api/v1/events?limit=500&latest=true",
  catalog: "/api/v1/catalog",
} as const;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request(
  path: string,
  signal?: AbortSignal,
  init?: RequestInit,
): Promise<unknown> {
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
      detail = string(record(await response.json()).detail);
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
    return await response.json();
  } catch {
    throw new ApiError("The daemon returned an invalid JSON response.");
  }
}

export type AttentionAction = "release" | "requeue" | "abort";

export async function resolveAttention(
  runId: string,
  action: AttentionAction,
): Promise<void> {
  await request(`/api/v1/runs/${encodeURIComponent(runId)}/attention`, undefined, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId, action }),
  });
}

export async function getHealth(signal?: AbortSignal): Promise<ProjectHealth> {
  const raw = await request(API.health, signal);
  const details = record(raw);
  return {
    status: requiredString(details.status, "status"),
    projectId: requiredString(details.project_id, "project_id"),
    projectName: requiredString(details.project_name, "project_name"),
    projectRoot: requiredString(details.project_root, "project_root"),
    details,
  };
}

export async function getRuns(signal?: AbortSignal): Promise<ProjectRun[]> {
  const raw = await request(API.runs, signal);
  const envelope = record(raw);
  const values = Array.isArray(raw)
    ? raw
    : array(envelope.items) ?? array(envelope.runs) ?? [];
  return values.map(normalizeRun).sort(compareRuns);
}

export async function getRun(
  runId: string,
  signal?: AbortSignal,
): Promise<ProjectRun> {
  const raw = await request(`/api/v1/runs/${encodeURIComponent(runId)}`, signal);
  const envelope = record(raw);
  const control = hasKeys(record(envelope.control))
    ? record(envelope.control)
    : envelope;
  const manifest = record(envelope.manifest);
  return normalizeRun({
    ...control,
    ...manifest,
    admission: control.admission,
    outcome: manifest.outcome ?? control.outcome,
    resources: envelope.resources,
  });
}

export async function getMeasurementPreview(
  runId: string,
  signal?: AbortSignal,
): Promise<MeasurementPreview> {
  const raw = await request(
    `/api/v1/runs/${encodeURIComponent(runId)}/measurements?limit=100`,
    signal,
  );
  const envelope = record(raw);
  return {
    items: (array(envelope.items) ?? []).map(record),
    nextOffset: number(envelope.next_offset),
  };
}

export async function getRunAnalyses(
  runId: string,
  signal?: AbortSignal,
): Promise<RunAnalysis[]> {
  const envelope = record(
    await request(
      `/api/v1/runs/${encodeURIComponent(runId)}/analyses`,
      signal,
    ),
  );
  return (array(envelope.items) ?? []).map((value) => {
    const item = record(value);
    const analysis = record(item.analysis);
    return {
      id:
        string(record(item.entry).id) ??
        string(analysis.key) ??
        "unidentified-analysis",
      title: string(analysis.title) ?? "Untitled analysis",
      key: string(analysis.key),
      stepId: string(analysis.step_id),
      outputs: (array(analysis.outputs) ?? []).map((output) => {
        const source = record(output);
        return {
          kind: string(source.kind) ?? "output",
          title: string(source.title) ?? "Untitled output",
          content: source.content,
        };
      }),
    };
  });
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
  let path: string;
  let format: RunContentPreview["format"] = "json";
  if (entry.role === "record") {
    path =
      `/api/v1/runs/${run}/records/${selector}/json` +
      `?expected_kind=${encodeURIComponent(entry.kind)}`;
  } else if (entry.role === "dataset") {
    path = `/api/v1/runs/${run}/datasets/${selector}`;
  } else {
    const artifactContentFormat = artifactFormat(entry);
    if (!artifactContentFormat) {
      throw new ApiError("This artifact does not have a browser-readable format.");
    }
    format = artifactContentFormat;
    const expectedKind = encodeURIComponent(entry.kind);
    path =
      `/api/v1/runs/${run}/artifacts/${selector}/${format}` +
      `?expected_kind=${expectedKind}`;
  }
  const envelope = record(await request(path, signal));
  return {
    entry: normalizeContentEntry(
      envelope.artifact ?? envelope.record ?? envelope.dataset ?? entry,
      0,
    ),
    format,
    content: envelope.content,
  };
}

export async function getEvents(signal?: AbortSignal): Promise<ProjectEvent[]> {
  const raw = await request(API.events, signal);
  const envelope = record(raw);
  const values = Array.isArray(raw)
    ? raw
    : array(envelope.items) ?? array(envelope.events) ?? [];
  return values.map(normalizeEvent).sort((left, right) => left.id - right.id);
}

export async function getCatalog(
  signal?: AbortSignal,
): Promise<ExperimentCatalog> {
  const raw = await request(API.catalog, signal);
  const envelope = record(raw);
  const values = array(envelope.experiments) ?? array(envelope.items) ?? [];
  return {
    revision: string(envelope.revision),
    experiments: values.map(normalizeExperiment),
  };
}

function normalizeRun(value: unknown): ProjectRun {
  const source = record(value);
  const admission = record(source.admission);
  const outcome = record(source.outcome);
  const requestRecord = record(admission.request ?? source.request);
  const planSummary = record(
    admission.plan_summary ?? source.plan_summary ?? source.plan,
  );
  const plan = hasKeys(record(planSummary.plan))
    ? record(planSummary.plan)
    : planSummary;
  const rawState =
    string(source.state) ?? string(source.lifecycle) ?? string(source.status);
  const result = string(outcome.result);
  const status = normalizeStatus(rawState, result);
  const runId =
    string(admission.run_id) ??
    string(source.run_id) ??
    string(source.id) ??
    "unidentified-run";
  const resources = normalizeResources(
    source.resources ??
      admission.resource_claims ??
      plan.run_resource_claims ??
      source.resource_claims,
  );
  const contents = normalizeContents(source.contents ?? plan.contents);
  const progressCompleted =
    number(plan.completed_points) ??
    number(plan.points_completed) ??
    number(source.completed_points);

  return {
    sequence: number(source.sequence),
    runId,
    experimentId:
      string(admission.experiment_id) ??
      string(plan.experiment_id) ??
      string(requestRecord.experiment_id) ??
      "Unspecified experiment",
    executionMode:
      string(admission.execution_mode) ??
      string(source.execution_mode) ??
      "local",
    status,
    stateLabel: statusLabel(status),
    createdAt:
      string(admission.admitted_at) ??
      string(source.created_at) ??
      string(source.accepted_at),
    updatedAt:
      string(source.updated_at) ??
      string(outcome.finished_at) ??
      string(admission.admitted_at),
    configHash:
      string(admission.config_content_hash) ??
      string(source.config_content_hash),
    attentionReason:
      string(source.attention_reason) ?? string(outcome.termination_reason),
    result,
    certainty: string(outcome.certainty),
    progressCompleted,
    plan: {
      pointCount: number(plan.point_count) ?? number(plan.points),
      coordinateIds: strings(plan.coordinate_ids),
      recordIds: strings(plan.record_ids),
    },
    resources,
    contents,
  };
}

function normalizeEvent(value: unknown, index: number): ProjectEvent {
  const source = record(value);
  const data = record(source.data);
  const manifest = record(data.manifest);
  const transition = record(data.transition);
  const payload = hasKeys(record(source.payload))
    ? record(source.payload)
    : hasKeys(data)
      ? data
      : source;

  return {
    id: number(source.event_id) ?? number(source.cursor) ?? index + 1,
    runId:
      string(source.run_id) ??
      string(data.run_id) ??
      string(manifest.run_id) ??
      string(transition.run_id),
    kind:
      string(source.kind) ??
      string(data.kind) ??
      string(transition.kind) ??
      "project_event",
    occurredAt:
      string(source.occurred_at) ??
      string(data.occurred_at) ??
      string(transition.occurred_at),
    payload,
  };
}

function normalizeExperiment(value: unknown): ExperimentDescriptor {
  const source = record(value);
  return {
    id: string(source.id) ?? "unidentified-experiment",
    version: string(source.version) ?? "unversioned",
    title:
      string(source.title) ??
      string(source.id) ??
      "Unidentified experiment",
    description: string(source.description),
    tags: strings(source.tags),
  };
}

function normalizeResources(value: unknown): ResourceClaim[] {
  return (array(value) ?? []).map((item) => {
    const source = record(item);
    const resource = hasKeys(record(source.resource))
      ? record(source.resource)
      : source;
    return {
      id: string(resource.id) ?? "unidentified-resource",
      kind: string(resource.kind) ?? "instrument",
      status: string(source.status),
    };
  });
}

function normalizeContents(value: unknown): ContentEntry[] {
  return (array(value) ?? []).map(normalizeContentEntry);
}

function normalizeContentEntry(value: unknown, index: number): ContentEntry {
  const source = record(value);
  const content = record(source.content);
  const role = string(source.role) ?? "content";
  const kind = string(source.kind) ?? "content";
  const mediaType =
    string(source.media_type) ??
    string(source.content_type) ??
    string(content.media_type);
  const filename = string(source.filename);
  return {
    id:
      string(source.id) ??
      string(source.content_id) ??
      string(source.ref) ??
      `${role}-${index + 1}`,
    role,
    kind,
    label:
      string(source.label) ??
      string(source.title) ??
      filename ??
      string(source.name) ??
      string(content.name) ??
      string(source.content_id) ??
      `${titleCase(role)} ${index + 1}`,
    detail: mediaType ?? kind,
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

function normalizeStatus(rawState?: string, result?: string): RunStatus {
  if (rawState === "attention_required") return "attention_required";
  if (rawState === "accepted" || rawState === "planned") return "accepted";
  if (rawState === "running") return "running";
  if (result === "succeeded" || rawState === "completed") return "succeeded";
  if (result === "failed" || rawState === "failed") return "failed";
  if (
    result === "cancelled" ||
    rawState === "cancelled" ||
    rawState === "interrupted"
  ) {
    return "cancelled";
  }
  if (rawState === "terminal") return "terminal";
  return "unknown";
}

function statusLabel(status: RunStatus): string {
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
    case "terminal":
      return "Finished";
    default:
      return "Unknown";
  }
}

function compareRuns(left: ProjectRun, right: ProjectRun): number {
  if (left.sequence !== undefined && right.sequence !== undefined) {
    return right.sequence - left.sequence;
  }
  return (right.updatedAt ?? "").localeCompare(left.updatedAt ?? "");
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function array(value: unknown): unknown[] | undefined {
  return Array.isArray(value) ? value : undefined;
}

function string(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function number(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function strings(value: unknown): string[] {
  return (array(value) ?? []).filter(
    (item): item is string => typeof item === "string",
  );
}

function requiredString(value: unknown, field: string): string {
  const result = string(value);
  if (!result) {
    throw new ApiError(`The daemon response is missing ${field}.`);
  }
  return result;
}

function hasKeys(value: Record<string, unknown>): boolean {
  return Object.keys(value).length > 0;
}

function titleCase(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

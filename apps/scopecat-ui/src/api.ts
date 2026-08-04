import type {
  AnalysisRecordOutput,
  DurableEvent,
  EventPage,
  MeasurementTracePreview,
  MeasurementTracePreviewQuery,
  RunContentEntry,
  RunControlView,
  RunManifest,
  RunResourceView,
  RunSummaryPage,
} from "./api-contract";
import { ApiError, apiClient, apiData } from "./api-client";
import type {
  ContentEntry,
  MeasurementPreview,
  MeasurementSlicePreview,
  ProjectEvent,
  ProjectHealth,
  ProjectRun,
  ProjectRunPage,
  PresentationRunStatus,
  RunAnalysis,
  RunAnalysisOutput,
  RunContentPreview,
  RunResource,
} from "./types";

type RunResourceRequirement =
  RunControlView["admission"]["plan"]["run_resource_requirements"][number];
export { ApiError } from "./api-client";

export async function resolveAttention(runId: string): Promise<void> {
  await apiData(
    apiClient.POST("/api/v1/runs/{run_id}/attention", {
      params: { path: { run_id: runId } },
    }),
  );
}

export async function getHealth(signal?: AbortSignal): Promise<ProjectHealth> {
  const response = await apiData(apiClient.GET("/api/v1/health", { signal }));
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
    await apiData(
      apiClient.GET("/api/v1/runs", {
        params: { query: { limit: 100 } },
        signal,
      }),
    ),
  );
}

export async function getOlderRuns(before: number, signal?: AbortSignal): Promise<ProjectRunPage> {
  return normalizeRunPage(
    await apiData(
      apiClient.GET("/api/v1/runs", {
        params: { query: { limit: 100, before } },
        signal,
      }),
    ),
  );
}

function normalizeRunPage(response: RunSummaryPage): ProjectRunPage {
  return {
    items: response.items.map((run) => normalizeRun(run.control, run.manifest)).sort(compareRuns),
    nextCursor: response.next_cursor ?? undefined,
  };
}

export async function getRun(runId: string, signal?: AbortSignal): Promise<ProjectRun> {
  const response = await apiData(
    apiClient.GET("/api/v1/runs/{run_id}", {
      params: { path: { run_id: runId } },
      signal,
    }),
  );
  return normalizeRun(response.control, response.manifest, response.resources ?? []);
}

export async function getMeasurementPreview(
  runId: string,
  offset = 0,
  signal?: AbortSignal,
): Promise<MeasurementPreview> {
  const response = await apiData(
    apiClient.GET("/api/v1/runs/{run_id}/measurements", {
      params: {
        path: { run_id: runId },
        query: { limit: 100, offset, include_schema: offset === 0 },
      },
      signal,
    }),
  );
  return {
    items: response.items ?? [],
    schema: response.dataset_schema ?? undefined,
    nextOffset: response.next_offset ?? undefined,
  };
}

export async function getMeasurementSlice(
  runId: string,
  fixedAxisIndices: Record<string, number>,
  variableIds: string[],
  signal?: AbortSignal,
): Promise<MeasurementSlicePreview> {
  const response = await apiData(
    apiClient.POST("/api/v1/runs/{run_id}/measurements/query", {
      params: { path: { run_id: runId } },
      body: {
        fixed_axis_indices: fixedAxisIndices,
        include_schema: false,
        limit: 4096,
        variable_ids: variableIds,
      },
      signal,
    }),
  );
  return {
    items: response.items,
    schema: response.dataset_schema ?? undefined,
    selectedPointCount: response.selected_point_count,
    truncated: response.truncated,
  };
}

export async function getMeasurementTracePreview(
  runId: string,
  selection: {
    observableId: string;
    coordinateId: string;
    recordingGroupId?: string;
    fixedAxisIndices: Record<string, number>;
    complexMode: MeasurementTracePreviewQuery["complex_mode"];
  },
  signal?: AbortSignal,
): Promise<MeasurementTracePreview> {
  return apiData(
    apiClient.POST("/api/v1/runs/{run_id}/measurements/traces/query", {
      params: { path: { run_id: runId } },
      body: {
        complex_mode: selection.complexMode,
        coordinate_id: selection.coordinateId,
        downsampling: "even",
        fixed_axis_indices: selection.fixedAxisIndices,
        max_samples: 4096,
        max_series: 32,
        observable_id: selection.observableId,
        recording_group_id: selection.recordingGroupId,
      },
      signal,
    }),
  );
}

export async function getRunAnalyses(runId: string, signal?: AbortSignal): Promise<RunAnalysis[]> {
  const response = await apiData(
    apiClient.GET("/api/v1/runs/{run_id}/analyses", {
      params: { path: { run_id: runId } },
      signal,
    }),
  );
  return (response.items ?? []).map(({ entry, analysis }) => ({
    id: entry.id,
    title: analysis.title,
    key: analysis.key ?? undefined,
    stepId: analysis.step_id ?? undefined,
    inputs: analysis.inputs ?? [],
    outputs: analysis.outputs.map(runAnalysisOutput),
  }));
}

function runAnalysisOutput(output: AnalysisRecordOutput): RunAnalysisOutput {
  const shared = {
    title: output.title,
    metadata: output.metadata ?? {},
  };
  if (output.kind === "table") {
    return { ...shared, kind: "table", content: output.content };
  }
  if (output.kind === "figure") {
    return { ...shared, kind: "figure", content: output.content };
  }
  return {
    ...shared,
    kind: "parameter_change_proposal",
    content: output.content,
  };
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
  if (entry.role === "record") {
    const response = await apiData(
      apiClient.GET("/api/v1/runs/{run_id}/records/{selector}/json", {
        params: {
          path: { run_id: runId, selector: entry.id },
          query: { expected_kind: entry.kind },
        },
        signal,
      }),
    );
    return {
      entry: normalizeContentEntry(response.record, 0),
      format: "json",
      content: response.content,
    };
  }
  if (entry.role === "dataset") {
    const response = await apiData(
      apiClient.GET("/api/v1/runs/{run_id}/datasets/{selector}", {
        params: { path: { run_id: runId, selector: entry.id } },
        signal,
      }),
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
  if (format === "text") {
    const response = await apiData(
      apiClient.GET("/api/v1/runs/{run_id}/artifacts/{selector}/text", {
        params: {
          path: { run_id: runId, selector: entry.id },
          query: { expected_kind: entry.kind },
        },
        signal,
      }),
    );
    return {
      entry: normalizeContentEntry(response.artifact, 0),
      format,
      content: response.content,
    };
  }
  const response = await apiData(
    apiClient.GET("/api/v1/runs/{run_id}/artifacts/{selector}/json", {
      params: {
        path: { run_id: runId, selector: entry.id },
        query: { expected_kind: entry.kind },
      },
      signal,
    }),
  );
  return {
    entry: normalizeContentEntry(response.artifact, 0),
    format,
    content: response.content,
  };
}

export async function getEvents(signal?: AbortSignal): Promise<ProjectEvent[]> {
  return normalizeEvents(
    await apiData(
      apiClient.GET("/api/v1/events", {
        params: { query: { limit: 500, latest: true } },
        signal,
      }),
    ),
  );
}

export async function getRunEvents(runId: string, signal?: AbortSignal): Promise<ProjectEvent[]> {
  return normalizeEvents(
    await apiData(
      apiClient.GET("/api/v1/events", {
        params: { query: { limit: 500, latest: true, run_id: runId } },
        signal,
      }),
    ),
  );
}

function normalizeEvents(response: EventPage): ProjectEvent[] {
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
    stage: manifest.stage
      ? {
          sequenceId: manifest.stage.sequence_id,
          index: manifest.stage.index,
          previousRunId: manifest.stage.previous_run_id ?? undefined,
        }
      : undefined,
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

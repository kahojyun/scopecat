import { apiClient, apiData } from "../api-client";
import type { ProjectEvent, ProjectHealth } from "../types";

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

export async function getEvents(signal?: AbortSignal): Promise<ProjectEvent[]> {
  const response = await apiData(
    apiClient.GET("/api/v1/events", {
      params: { query: { limit: 500, latest: true } },
      signal,
    }),
  );
  return response.items
    .map((event) => ({
      id: event.event_id,
      runId: event.run_id ?? undefined,
      kind: event.kind,
      occurredAt: event.occurred_at,
      payload: event.payload ?? {},
    }))
    .sort((left, right) => left.id - right.id);
}

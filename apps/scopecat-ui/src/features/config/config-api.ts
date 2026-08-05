import { apiClient, apiData } from "../../api-client";
import type {
  ConfigDraftCommand,
  ConfigDraftPreview,
  ConfigProfileSnapshot,
  ConfigRegistryEntry,
  ConfigRegistryOverview,
  ConfigPublishCommand,
  ConfigPublishReceipt,
} from "../../api-contract";
import type { components } from "../../api-schema";

export interface ConfigSnapshotSummary {
  id: string;
  primaryEntityId: string;
  parameterCount: number;
  instrumentCount: number;
}

export interface ConfigRegistryEntryDetail {
  entry: ConfigRegistryEntry;
  config: ConfigProfileSnapshot;
  summary: ConfigSnapshotSummary;
}

export async function getConfigRegistry(signal?: AbortSignal): Promise<ConfigRegistryOverview> {
  const [registry, activations] = await Promise.all([
    apiData(apiClient.GET("/api/v1/config-registry", { signal })),
    apiData(apiClient.GET("/api/v1/config-registry/activations", { signal })),
  ]);
  return {
    ...registry,
    entries: [...registry.entries].sort((left, right) =>
      (right.recorded_at ?? "").localeCompare(left.recorded_at ?? ""),
    ),
    activation_history: [...(activations.items ?? [])].sort(
      (left, right) => right.generation - left.generation,
    ),
  };
}

export async function getConfigRegistryEntry(
  entryId: string,
  signal?: AbortSignal,
): Promise<ConfigRegistryEntryDetail> {
  const response = await apiData(
    apiClient.GET("/api/v1/config-registry/entries/{entry_id}", {
      params: { path: { entry_id: entryId } },
      signal,
    }),
  );
  const config = configSnapshot(response.config);
  return {
    entry: response.entry,
    config,
    summary: summarizeConfigSnapshot(config),
  };
}

export async function activateConfigEntry(
  command: components["schemas"]["ConfigEntryActivationCommand"],
): Promise<void> {
  await apiData(apiClient.POST("/api/v1/config-registry/active", { body: command }));
}

export async function undoConfig(
  command: components["schemas"]["ConfigUndoCommand"],
): Promise<void> {
  await apiData(apiClient.POST("/api/v1/config-registry/undo", { body: command }));
}

export async function previewConfigDraft(command: ConfigDraftCommand): Promise<ConfigDraftPreview> {
  const response = await apiData(
    apiClient.POST("/api/v1/config-registry/drafts/preview", {
      body: command,
    }),
  );
  return response as ConfigDraftPreview;
}

export async function setConfigDefault(
  command: ConfigPublishCommand,
): Promise<ConfigPublishReceipt> {
  const response = await apiData(
    apiClient.POST("/api/v1/config-registry/default", {
      body: command,
    }),
  );
  return response as ConfigPublishReceipt;
}

function summarizeConfigSnapshot(config: ConfigProfileSnapshot): ConfigSnapshotSummary {
  return {
    id: config.id,
    primaryEntityId: config.system.primary_entity_id,
    parameterCount: config.parameter_snapshot.values?.length ?? 0,
    instrumentCount: config.system.instrument_registry.instruments.length,
  };
}

export function parseConfigProfileJson(textValue: string): ConfigProfileSnapshot {
  let parsed: unknown;
  try {
    parsed = JSON.parse(textValue);
  } catch {
    throw new Error("The selected file is not valid JSON.");
  }
  const profile = object(parsed, "selected config snapshot");
  const formatVersion = optionalText(profile.format_version);
  if (formatVersion !== "scopecat.config_snapshot.v9") {
    throw new Error(
      `Unsupported config snapshot format: ${formatVersion ?? "missing format_version"}.`,
    );
  }
  if (!optionalText(profile.id)) {
    throw new Error("The config snapshot is missing its id.");
  }
  if (!isObject(profile.system)) {
    throw new Error("The config snapshot is missing its system definition.");
  }
  if (!isObject(profile.parameter_snapshot)) {
    throw new Error("The config snapshot is missing its parameter values.");
  }
  const snapshot = { ...profile };
  delete snapshot.format_version;
  return snapshot as ConfigProfileSnapshot;
}

function configSnapshot(source: unknown): ConfigProfileSnapshot {
  // OpenAPI emits separate input/output aliases for the same JSON snapshot.
  return source as ConfigProfileSnapshot;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (!isObject(value)) throw new Error(`${label} must be an object.`);
  return value;
}

function optionalText(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

import { request } from "../../api";
import type {
  ConfigDraftCommand,
  ConfigDraftPreview,
  ConfigProfileSnapshot,
  ConfigRegistryEntry,
  ConfigRegistryOverview,
  ConfigPublishCommand,
  ConfigPublishReceipt,
  DaemonUiApi,
} from "../../api-contract";

const CONFIG_API = "/api/v1/config-registry";

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
    request<DaemonUiApi["configRegistry"]>(CONFIG_API, signal),
    request<DaemonUiApi["configActivations"]>(`${CONFIG_API}/activations`, signal),
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
  const response = await request<DaemonUiApi["configEntry"]>(
    `${CONFIG_API}/entries/${encodeURIComponent(entryId)}`,
    signal,
  );
  const config = configSnapshot(response.config);
  return {
    entry: response.entry,
    config,
    summary: summarizeConfigSnapshot(config),
  };
}

export async function activateConfigEntry(
  command: DaemonUiApi["configActivationCommand"],
): Promise<void> {
  await request<DaemonUiApi["configActivationReceipt"]>(
    `${CONFIG_API}/active`,
    undefined,
    jsonRequest(command),
  );
}

export async function undoConfig(command: DaemonUiApi["configUndoCommand"]): Promise<void> {
  await request<DaemonUiApi["configUndoReceipt"]>(
    `${CONFIG_API}/undo`,
    undefined,
    jsonRequest(command),
  );
}

export async function previewConfigDraft(command: ConfigDraftCommand): Promise<ConfigDraftPreview> {
  const response = await request<DaemonUiApi["configDraftPreview"]>(
    `${CONFIG_API}/drafts/preview`,
    undefined,
    jsonRequest(command),
  );
  return response as ConfigDraftPreview;
}

export async function setConfigDefault(
  command: ConfigPublishCommand,
): Promise<ConfigPublishReceipt> {
  const response = await request<DaemonUiApi["configPublishReceipt"]>(
    `${CONFIG_API}/default`,
    undefined,
    jsonRequest(command),
  );
  return response as ConfigPublishReceipt;
}

export function summarizeConfigSnapshot(config: ConfigProfileSnapshot): ConfigSnapshotSummary {
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
  if (formatVersion !== "scopecat.config_snapshot.v4") {
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

function configSnapshot(source: DaemonUiApi["configEntry"]["config"]): ConfigProfileSnapshot {
  // OpenAPI emits separate input/output aliases for the same JSON snapshot.
  return source as ConfigProfileSnapshot;
}

function jsonRequest(body: object): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
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

import { request } from "../../api";
import type {
  ConfigDraftCommand,
  ConfigDraftDefaultCommand,
  ConfigDraftDefaultReceipt,
  ConfigDraftPreview,
  ConfigDraftRegistrationCommand,
  ConfigDraftRegistrationReceipt,
  ConfigProfileSnapshot,
  ConfigRegistryEntry,
  ConfigRegistryOverview,
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
  const registry = await request<DaemonUiApi["configRegistry"]>(CONFIG_API, signal);
  return {
    ...registry,
    entries: [...registry.entries].sort((left, right) =>
      (right.registered_at ?? "").localeCompare(left.registered_at ?? ""),
    ),
    active_state: registry.active_state
      ? {
          ...registry.active_state,
          history: [...(registry.active_state.history ?? [])].sort(
            (left, right) => right.generation - left.generation,
          ),
        }
      : registry.active_state,
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

export async function rollbackConfig(command: DaemonUiApi["configRollbackCommand"]): Promise<void> {
  await request<DaemonUiApi["configRollbackReceipt"]>(
    `${CONFIG_API}/rollback`,
    undefined,
    jsonRequest(command),
  );
}

export async function importConfigProfile(
  command: DaemonUiApi["configImportCommand"],
): Promise<void> {
  await request<DaemonUiApi["configImportedEntry"]>(
    `${CONFIG_API}/entries`,
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

export async function registerConfigDraft(
  command: ConfigDraftRegistrationCommand,
): Promise<ConfigDraftRegistrationReceipt> {
  const response = await request<DaemonUiApi["configDraftRegistrationReceipt"]>(
    `${CONFIG_API}/drafts/register`,
    undefined,
    jsonRequest(command),
  );
  return response as ConfigDraftRegistrationReceipt;
}

export async function setConfigDraftDefault(
  command: ConfigDraftDefaultCommand,
): Promise<ConfigDraftDefaultReceipt> {
  const response = await request<DaemonUiApi["configDraftDefaultReceipt"]>(
    `${CONFIG_API}/drafts/set-default`,
    undefined,
    jsonRequest(command),
  );
  return response as ConfigDraftDefaultReceipt;
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
  if (formatVersion !== "scopecat.config_snapshot.v1") {
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

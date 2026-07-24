import { ApiError, request } from "./api";
import type {
  ConfigActivationRecord,
  ConfigCommand,
  ConfigRegistryEntry,
  ConfigRegistryEntryDetail,
  ConfigRegistryOverview,
  ConfigSnapshotSummary,
  ImportConfigCommand,
} from "./config-types";

const CONFIG_API = "/api/v1/config-registry";

export async function getConfigRegistry(
  signal?: AbortSignal,
): Promise<ConfigRegistryOverview> {
  const activeRequest = request(`${CONFIG_API}/active`, signal).catch(
    (error: unknown) => {
      if (error instanceof ApiError && error.status === 404) return undefined;
      throw error;
    },
  );
  const [registry, active] = await Promise.all([
    request(CONFIG_API, signal),
    activeRequest,
  ]);
  return normalizeConfigRegistryOverview({
    ...record(registry),
    active,
  });
}

export async function getConfigRegistryEntry(
  entryId: string,
  signal?: AbortSignal,
): Promise<ConfigRegistryEntryDetail> {
  const envelope = record(
    await request(
      `${CONFIG_API}/entries/${encodeURIComponent(entryId)}`,
      signal,
    ),
  );
  return {
    entry: normalizeEntry(envelope.entry),
    snapshot: normalizeSnapshot(envelope.config),
  };
}

export async function activateConfigEntry(
  entryId: string,
  command: ConfigCommand,
): Promise<void> {
  await request(
    `${CONFIG_API}/active`,
    undefined,
    jsonRequest({
      entry_id: entryId,
      ...commandPayload(command),
    }),
  );
}

export async function rollbackConfig(command: ConfigCommand): Promise<void> {
  await request(
    `${CONFIG_API}/rollback`,
    undefined,
    jsonRequest(commandPayload(command)),
  );
}

export async function importConfigProfile(
  command: ImportConfigCommand,
): Promise<void> {
  await request(
    `${CONFIG_API}/entries`,
    undefined,
    jsonRequest({
      entry_id: command.entryId,
      registered_by: command.registeredBy,
      note: command.note ?? "",
      config: command.config,
    }),
  );
}

export function normalizeConfigRegistryOverview(
  value: unknown,
): ConfigRegistryOverview {
  const envelope = record(value);
  const index = record(envelope.index ?? envelope.registry);
  const activeEnvelope = record(envelope.active);
  const activeState = record(
    activeEnvelope.active_state ?? envelope.active_state ?? activeEnvelope,
  );
  const activeSnapshot = record(
    activeEnvelope.config ??
      envelope.active_config ??
      activeState.config ??
      activeState.snapshot,
  );
  const historyValues =
    array(activeState.history) ?? array(envelope.history) ?? [];
  const entryValues =
    array(index.entries) ?? array(envelope.entries) ?? array(envelope.registry) ?? [];
  const activeEntryId =
    string(activeState.active_entry_id) ??
    string(activeState.entry_id) ??
    string(activeState.entryId);
  const activeContentHash =
    string(activeState.active_entry_content_hash) ??
    string(activeState.content_hash) ??
    string(activeState.contentHash);
  const generation = number(activeState.generation);

  return {
    active:
      activeEntryId && activeContentHash && generation !== undefined
        ? {
            generation,
            entryId: activeEntryId,
            contentHash: activeContentHash,
            updatedAt:
              string(activeState.updated_at) ?? string(activeState.updatedAt),
            snapshot: hasKeys(activeSnapshot)
              ? normalizeSnapshot(activeSnapshot)
              : undefined,
          }
        : undefined,
    entries: entryValues.map(normalizeEntry).sort(compareRegisteredEntries),
    history: historyValues.map(normalizeActivation).sort(compareActivations),
  };
}

export function parseConfigProfileJson(text: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error("The selected file is not valid JSON.");
  }
  const profile = record(parsed);
  if (!hasKeys(profile)) {
    throw new Error("The selected file must contain one config snapshot object.");
  }
  const schemaVersion = string(profile.schema_version);
  if (schemaVersion === "scopecat.config_profile.v2") {
    throw new Error(
      "This split config_profile.v2 file must be loaded by Python before importing its config_profile_snapshot.v2 result.",
    );
  }
  if (
    schemaVersion !== "scopecat.config_profile_snapshot.v2"
  ) {
    throw new Error(
      `Unsupported config snapshot schema: ${schemaVersion ?? "missing schema_version"}.`,
    );
  }
  if (!string(profile.id)) {
    throw new Error("The config snapshot is missing its id.");
  }
  if (!hasKeys(record(profile.system))) {
    throw new Error("The config snapshot is missing its system definition.");
  }
  if (!hasKeys(record(profile.environment))) {
    throw new Error("The config snapshot is missing its environment definition.");
  }
  if (!hasKeys(record(profile.parameter_snapshot))) {
    throw new Error("The config snapshot is missing its parameter values.");
  }
  return profile;
}

function normalizeEntry(value: unknown): ConfigRegistryEntry {
  const source = record(value);
  const provenance = record(source.source);
  const proposalEvidence =
    array(provenance.proposal_evidence) ??
    array(provenance.proposalEvidence) ??
    [];
  const snapshot = record(source.config ?? source.snapshot);
  return {
    id: string(source.id) ?? "unidentified-config",
    contentHash:
      string(source.content_hash) ??
      string(source.contentHash) ??
      "unreported",
    configRef: string(source.config_ref) ?? string(source.configRef),
    registeredBy:
      string(source.registered_by) ?? string(source.registeredBy),
    registeredAt:
      string(source.registered_at) ?? string(source.registeredAt),
    note: string(source.note),
    source: {
      kind:
        string(provenance.kind) ??
        string(source.source_kind) ??
        "direct_config_profile",
      runId: string(provenance.run_id) ?? string(provenance.runId),
      proposalIds:
        strings(provenance.proposal_ids) ??
        proposalEvidence
          .map((item) => string(record(item).proposal_id))
          .filter((item): item is string => item !== undefined),
    },
    snapshot: hasKeys(snapshot) ? normalizeSnapshot(snapshot) : undefined,
  };
}

function normalizeActivation(value: unknown): ConfigActivationRecord {
  const source = record(value);
  const action = string(source.action);
  return {
    id: string(source.id) ?? "unidentified-activation",
    generation: number(source.generation) ?? 0,
    action: action === "rollback" ? "rollback" : "activation",
    entryId:
      string(source.entry_id) ??
      string(source.entryId) ??
      "unidentified-config",
    entryContentHash:
      string(source.entry_content_hash) ??
      string(source.entryContentHash) ??
      "unreported",
    previousEntryId:
      string(source.previous_entry_id) ?? string(source.previousEntryId),
    operator: string(source.operator),
    note: string(source.note),
    recordedAt: string(source.recorded_at) ?? string(source.recordedAt),
  };
}

function normalizeSnapshot(value: unknown): ConfigSnapshotSummary {
  const source = record(value);
  const system = record(source.system);
  const environment = record(source.environment);
  const parameterSnapshot = record(
    source.parameter_snapshot ?? source.parameterSnapshot,
  );
  const instruments = record(
    system.instrument_registry ?? system.instrumentRegistry,
  );
  const connections = record(
    environment.connection_profile ?? environment.connectionProfile,
  );
  return {
    id: string(source.id) ?? "unidentified-config",
    labId:
      string(system.workspace_id) ??
      string(system.workspaceId) ??
      string(source.workspace_id),
    primaryEntityId:
      string(system.primary_entity_id) ??
      string(system.primaryEntityId) ??
      string(source.primary_entity_id),
    parameterCount: array(parameterSnapshot.values)?.length ?? 0,
    instrumentCount: array(instruments.instruments)?.length ?? 0,
    connectionCount: array(connections.connections)?.length ?? 0,
  };
}

function compareRegisteredEntries(
  left: ConfigRegistryEntry,
  right: ConfigRegistryEntry,
): number {
  return (right.registeredAt ?? "").localeCompare(left.registeredAt ?? "");
}

function compareActivations(
  left: ConfigActivationRecord,
  right: ConfigActivationRecord,
): number {
  return right.generation - left.generation;
}

function commandPayload(command: ConfigCommand): Record<string, unknown> {
  return {
    operator: command.operator,
    note: command.note ?? "",
    expected_generation: command.expectedGeneration,
  };
}

function jsonRequest(body: Record<string, unknown>): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function array(value: unknown): unknown[] | undefined {
  return Array.isArray(value) ? value : undefined;
}

function strings(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value.filter((item): item is string => typeof item === "string");
}

function string(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function number(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function hasKeys(value: Record<string, unknown>): boolean {
  return Object.keys(value).length > 0;
}

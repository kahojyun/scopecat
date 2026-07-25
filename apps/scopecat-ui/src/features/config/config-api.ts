import { request } from "../../api";
import type {
  DaemonUiApi,
  EntityRef as WireEntityRef,
  ExternalLocation as WireExternalLocation,
  Quantity as WireQuantity,
} from "../../api-contract";
import type {
  ActiveConfigState,
  ConfigActivationRecord,
  ConfigCommand,
  ConfigDraftCommand,
  ConfigDraftDefaultCommand,
  ConfigDraftDefaultReceipt,
  ConfigDraftPreview,
  ConfigDraftRegistrationCommand,
  ConfigDraftRegistrationReceipt,
  ConfigParameterUpdate,
  ConfigProfileSnapshot,
  ConfigProblem,
  ConfigProblemLocation,
  ConfigRegistryEntry,
  ConfigRegistryEntryDetail,
  ConfigRegistryOverview,
  ConfigRegistrySource,
  ConfigSnapshotSummary,
  EnvironmentSpec,
  ExternalLocation,
  ImportConfigCommand,
  JsonObject,
  ParameterAtom,
  ParameterCatalog,
  ParameterDefinition,
  ParameterEntity,
  ParameterScalarType,
  ParameterSnapshot,
  ParameterTableColumn,
  ParameterValueDelta,
  ParameterValueType,
  StoredParameterValue,
  SystemSpec,
  Topology,
} from "./config-types";

const CONFIG_API = "/api/v1/config-registry";

type WireRegistry = DaemonUiApi["configRegistry"];
type WireRegistryEntry = NonNullable<WireRegistry["entries"]>[number];
type WireActiveState = NonNullable<WireRegistry["active_state"]>;
type WireActivation = NonNullable<WireActiveState["history"]>[number];
type WireConfig = DaemonUiApi["configEntry"]["config"];
type WireSystem = WireConfig["system"];
type WireTopology = WireSystem["topology"];
type WireParameterCatalog = WireSystem["parameter_catalog"];
type WireParameterDefinition = NonNullable<WireParameterCatalog["definitions"]>[number];
type WireValueType = WireParameterDefinition["value_type"];
type WireScalarType =
  | Extract<WireValueType, { shape: "scalar" }>["atom"]
  | Extract<WireValueType, { shape: "series" }>["item_type"]
  | Extract<WireValueType, { shape: "table" }>["columns"][number]["value_type"];
type WireStoredParameterValue = NonNullable<WireConfig["parameter_snapshot"]["values"]>[number];
type WireParameterDelta = NonNullable<DaemonUiApi["configDraftPreview"]["deltas"]>[number];
type WireProblem = NonNullable<DaemonUiApi["configDraftPreview"]["problems"]>[number];
type WireParameterAtom = null | boolean | number | string | WireQuantity | WireEntityRef;

export async function getConfigRegistry(signal?: AbortSignal): Promise<ConfigRegistryOverview> {
  return normalizeConfigRegistryOverview(
    await request<DaemonUiApi["configRegistry"]>(CONFIG_API, signal),
  );
}

export async function getConfigRegistryEntry(
  entryId: string,
  signal?: AbortSignal,
): Promise<ConfigRegistryEntryDetail> {
  const response = await request<DaemonUiApi["configEntry"]>(
    `${CONFIG_API}/entries/${encodeURIComponent(entryId)}`,
    signal,
  );
  const config = normalizeConfigProfileSnapshot(response.config);
  return {
    entry: normalizeEntry(response.entry),
    config,
    summary: summarizeConfigSnapshot(config),
  };
}

export async function activateConfigEntry(entryId: string, command: ConfigCommand): Promise<void> {
  const payload: DaemonUiApi["configActivationCommand"] = {
    entry_id: entryId,
    ...commandPayload(command),
  };
  await request<DaemonUiApi["configActivationReceipt"]>(
    `${CONFIG_API}/active`,
    undefined,
    jsonRequest(payload),
  );
}

export async function rollbackConfig(command: ConfigCommand): Promise<void> {
  const payload: DaemonUiApi["configRollbackCommand"] = {
    ...commandPayload(command),
  };
  await request<DaemonUiApi["configRollbackReceipt"]>(
    `${CONFIG_API}/rollback`,
    undefined,
    jsonRequest(payload),
  );
}

export async function importConfigProfile(command: ImportConfigCommand): Promise<void> {
  const payload: DaemonUiApi["configImportCommand"] = {
    entry_id: command.entryId,
    registered_by: command.registeredBy,
    note: command.note ?? "",
    config: command.config as unknown as DaemonUiApi["configImportCommand"]["config"],
  };
  await request<DaemonUiApi["configImportReceipt"]>(
    `${CONFIG_API}/entries`,
    undefined,
    jsonRequest(payload),
  );
}

export async function previewConfigDraft(command: ConfigDraftCommand): Promise<ConfigDraftPreview> {
  return normalizeConfigDraftPreview(
    await request<DaemonUiApi["configDraftPreview"]>(
      `${CONFIG_API}/drafts/preview`,
      undefined,
      jsonRequest(configDraftPayload(command)),
    ),
  );
}

export async function registerConfigDraft(
  command: ConfigDraftRegistrationCommand,
): Promise<ConfigDraftRegistrationReceipt> {
  const response = await request<DaemonUiApi["configDraftRegistrationReceipt"]>(
    `${CONFIG_API}/drafts/register`,
    undefined,
    jsonRequest(configDraftRegistrationPayload(command)),
  );
  return {
    entry: normalizeEntry(response.entry),
    resultContentHash: response.result_content_hash,
    deltas: response.deltas.map(normalizeParameterDelta),
  };
}

export async function setConfigDraftDefault(
  command: ConfigDraftDefaultCommand,
): Promise<ConfigDraftDefaultReceipt> {
  const payload: DaemonUiApi["configDraftDefaultCommand"] = {
    registration: configDraftRegistrationPayload(command.registration),
    operator: command.operator,
    activation_note: command.activationNote,
  };
  const response = await request<DaemonUiApi["configDraftDefaultReceipt"]>(
    `${CONFIG_API}/drafts/set-default`,
    undefined,
    jsonRequest(payload),
  );
  return {
    entry: normalizeEntry(response.entry),
    resultContentHash: response.result_content_hash,
    deltas: response.deltas.map(normalizeParameterDelta),
    activeState: normalizeActiveState(response.active_state),
    activation: normalizeActivation(response.activation),
  };
}

export function normalizeConfigDraftPreview(
  source: DaemonUiApi["configDraftPreview"],
): ConfigDraftPreview {
  return {
    valid: source.valid,
    baseEntry: normalizeEntry(source.base_entry),
    baseGeneration: source.base_generation,
    baseContentHash: source.base_content_hash,
    config: source.config ? normalizeConfigProfileSnapshot(source.config) : undefined,
    resultContentHash: source.result_content_hash ?? undefined,
    deltas: (source.deltas ?? []).map(normalizeParameterDelta),
    problems: (source.problems ?? []).map(normalizeProblem),
  };
}

export function normalizeConfigRegistryOverview(source: WireRegistry): ConfigRegistryOverview {
  const entries = (source.entries ?? []).map(normalizeEntry).sort(compareRegisteredEntries);
  if (!source.active_state) {
    return { active: undefined, entries, history: [] };
  }
  return {
    active: normalizeActiveState(source.active_state),
    entries,
    history: (source.active_state.history ?? []).map(normalizeActivation).sort(compareActivations),
  };
}

export function normalizeConfigProfileSnapshot(source: WireConfig): ConfigProfileSnapshot {
  return {
    id: source.id,
    system: normalizeSystem(source.system),
    environment: normalizeEnvironment(source.environment),
    parameterSnapshot: normalizeParameterSnapshot(source.parameter_snapshot),
    raw: source as unknown as JsonObject,
  };
}

export function summarizeConfigSnapshot(config: ConfigProfileSnapshot): ConfigSnapshotSummary {
  return {
    id: config.id,
    primaryEntityId: config.system.primaryEntityId,
    parameterCount: config.parameterSnapshot.values.length,
    instrumentCount: config.system.instruments.length,
    connectionCount: config.environment.connections.length,
  };
}

export function parseConfigProfileJson(textValue: string): JsonObject {
  let parsed: unknown;
  try {
    parsed = JSON.parse(textValue);
  } catch {
    throw new Error("The selected file is not valid JSON.");
  }
  const profile = object(parsed, "selected config snapshot");
  const formatVersion = optionalText(profile.format_version);
  if (formatVersion === "scopecat.config_profile_manifest.v1") {
    throw new Error(
      "This split config profile manifest must be loaded by Python before importing its config snapshot.",
    );
  }
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
  if (!isObject(profile.environment)) {
    throw new Error("The config snapshot is missing its environment definition.");
  }
  if (!isObject(profile.parameter_snapshot)) {
    throw new Error("The config snapshot is missing its parameter values.");
  }
  const snapshot = { ...profile };
  delete snapshot.format_version;
  return snapshot as JsonObject;
}

function normalizeEntry(source: WireRegistryEntry): ConfigRegistryEntry {
  return {
    id: source.id,
    contentHash: source.content_hash,
    configRef: source.config_ref,
    registeredBy: source.registered_by,
    registeredAt: source.registered_at!,
    note: source.note || undefined,
    source: normalizeRegistrySource(source.source),
  };
}

function normalizeRegistrySource(source: WireRegistryEntry["source"]): ConfigRegistrySource {
  switch (source.kind) {
    case "candidate_config":
      return {
        kind: source.kind,
        runId: source.run_id,
        proposalIds: source.proposal_evidence.map((item) => item.proposal_id),
        baseContentHash: source.base_config_content_hash,
      };
    case "manual_parameter_updates":
      return {
        kind: source.kind,
        proposalIds: [],
        baseEntryId: source.base_entry_id,
        baseContentHash: source.base_config_content_hash,
        baseGeneration: source.base_registry_generation,
      };
    case "direct_config_profile":
    case undefined:
      return { kind: "direct_config_profile", proposalIds: [] };
  }
}

function normalizeActivation(source: WireActivation): ConfigActivationRecord {
  return {
    id: source.id,
    generation: source.generation,
    action: source.action,
    entryId: source.entry_id,
    entryContentHash: source.entry_content_hash,
    previousEntryId: source.previous_entry_id ?? undefined,
    operator: source.operator,
    note: source.note || undefined,
    recordedAt: source.recorded_at!,
  };
}

function normalizeActiveState(source: WireActiveState): ActiveConfigState {
  return {
    generation: source.generation,
    entryId: source.active_entry_id,
    contentHash: source.active_entry_content_hash,
    updatedAt: source.updated_at,
  };
}

function normalizeSystem(source: WireSystem): SystemSpec {
  return {
    id: source.id,
    primaryEntityId: source.primary_entity_id,
    topology: normalizeTopology(source.topology),
    instruments: source.instrument_registry.instruments.map((instrument) => ({
      id: instrument.id,
      kind: instrument.kind,
    })),
    routing: (source.routing?.bindings ?? []).map((binding) => ({
      instrumentId: binding.instrument_id,
      capability: binding.capability,
      entityId: binding.entity_id ?? undefined,
      channelId: binding.channel_id ?? undefined,
      metadata: metadata(binding.metadata),
    })),
    domainTarget: source.domain_target
      ? {
          id: source.domain_target.id,
          kind: source.domain_target.kind,
          instrumentIds: source.domain_target.instrument_ids ?? [],
        }
      : undefined,
    parameterCatalog: normalizeParameterCatalog(source.parameter_catalog),
  };
}

function normalizeTopology(source: WireTopology): Topology {
  return {
    entities: (source.entities ?? []).map(normalizeEntity),
    devices: source.devices.map((device) => ({
      id: device.id,
      kind: device.kind!,
      channels: device.channels ?? [],
    })),
    links: (source.links ?? []).map((link) => ({
      id: link.id,
      endpoints: link.endpoints,
      kind: link.kind!,
    })),
    lines: (source.lines ?? []).map((line) => ({
      id: line.id,
      kind: line.kind,
      signal: line.signal ?? undefined,
      endpoints: line.endpoints ?? [],
      metadata: metadata(line.metadata),
    })),
    channels: (source.channels ?? []).map((channel) => ({
      id: channel.id,
      kind: channel.kind,
      deviceId: channel.device_id ?? undefined,
      direction: channel.direction ?? undefined,
      signal: channel.signal ?? undefined,
      port: channel.port ?? undefined,
      lineId: channel.line_id ?? undefined,
      groupIds: channel.group_ids ?? [],
      metadata: metadata(channel.metadata),
    })),
    groups: (source.groups ?? []).map((group) => ({
      id: group.id,
      kind: group.kind,
      members: group.members ?? [],
      metadata: metadata(group.metadata),
    })),
  };
}

function normalizeEnvironment(source: WireConfig["environment"]): EnvironmentSpec {
  return {
    id: source.id,
    connections: (source.connection_profile?.connections ?? []).map((connection) => ({
      id: connection.id,
      instrumentId: connection.instrument_id,
      kind: connection.kind!,
      resourceHint: connection.resource_hint ?? undefined,
    })),
  };
}

function normalizeParameterCatalog(source: WireParameterCatalog): ParameterCatalog {
  return {
    id: source.id,
    definitions: (source.definitions ?? []).map(normalizeParameterDefinition),
    metadata: metadata(source.metadata),
  };
}

function normalizeParameterDefinition(source: WireParameterDefinition): ParameterDefinition {
  return {
    id: source.id,
    valueType: normalizeValueType(source.value_type),
    description: source.description ?? undefined,
    metadata: metadata(source.metadata),
  };
}

function normalizeValueType(source: WireValueType): ParameterValueType {
  switch (source.shape) {
    case "scalar":
      return { shape: source.shape, atom: normalizeScalarType(source.atom) };
    case "series":
      return {
        shape: source.shape,
        itemType: normalizeScalarType(source.item_type),
        minLength: source.min_length ?? 0,
        maxLength: source.max_length ?? undefined,
      };
    case "table":
      return {
        shape: source.shape,
        columns: source.columns.map(normalizeTableColumn),
        primaryKey: source.primary_key ?? [],
        minRows: source.min_rows ?? 0,
        maxRows: source.max_rows ?? undefined,
      };
  }
}

function normalizeTableColumn(
  source: Extract<WireValueType, { shape: "table" }>["columns"][number],
): ParameterTableColumn {
  return {
    id: source.id,
    valueType: normalizeScalarType(source.value_type),
    required: source.required ?? true,
  };
}

function normalizeScalarType(source: WireScalarType): ParameterScalarType {
  const nullable = source.nullable ?? false;
  switch (source.type) {
    case "bool":
      return { type: source.type, nullable };
    case "int":
      return {
        type: source.type,
        nullable,
        minimum: source.minimum,
        maximum: source.maximum,
      };
    case "float":
      return {
        type: source.type,
        nullable,
        minimum: source.minimum,
        maximum: source.maximum,
        finite: source.finite ?? true,
      };
    case "string":
      return {
        type: source.type,
        nullable,
        minLength: source.min_length ?? 0,
        maxLength: source.max_length,
        pattern: source.pattern,
        choices: source.choices,
      };
    case "quantity":
      return {
        type: source.type,
        nullable,
        dimension: source.dimension,
        unit: source.unit,
        minimum: source.minimum,
        maximum: source.maximum,
        finite: source.finite ?? true,
      };
    case "entity":
      return {
        type: source.type,
        nullable,
        entityKind: source.entity_kind,
      };
  }
}

function normalizeParameterSnapshot(source: WireConfig["parameter_snapshot"]): ParameterSnapshot {
  return {
    id: source.id,
    values: (source.values ?? []).map(normalizeStoredParameterValue),
    metadata: metadata(source.metadata),
  };
}

function normalizeStoredParameterValue(source: WireStoredParameterValue): StoredParameterValue {
  const common = {
    id: source.id,
    sourceLocation: normalizeOptionalLocation(source.source_location),
    metadata: metadata(source.metadata),
  };
  switch (source.shape) {
    case "scalar":
      return {
        ...common,
        shape: source.shape,
        value: normalizeParameterAtom(source.value),
      };
    case "series":
      return {
        ...common,
        shape: source.shape,
        items: (source.items ?? []).map(normalizeParameterAtom),
        itemLocations: (source.item_locations ?? []).map(normalizeLocation),
      };
    case "table":
      return {
        ...common,
        shape: source.shape,
        rows: (source.rows ?? []).map((row) =>
          Object.fromEntries(
            Object.entries(row).map(([column, cell]) => [column, normalizeParameterAtom(cell)]),
          ),
        ),
        rowLocations: (source.row_locations ?? []).map(normalizeLocation),
      };
    case undefined:
      throw new Error("The daemon returned a parameter value without its shape.");
  }
}

function normalizeParameterAtom(value: unknown): ParameterAtom {
  if (!isObject(value)) {
    return value as null | boolean | number | string;
  }
  if ("value" in value) {
    return {
      value: value.value as number,
      unit: value.unit as string,
    };
  }
  return normalizeEntity(value);
}

function normalizeEntity(value: unknown): ParameterEntity {
  const source = value as { id: string; kind?: string | null; metadata?: unknown };
  return {
    id: source.id,
    kind: source.kind ?? undefined,
    metadata: metadata(source.metadata),
  };
}

function normalizeOptionalLocation(value: unknown): ExternalLocation | undefined {
  return value === null || value === undefined ? undefined : normalizeLocation(value);
}

function normalizeLocation(value: unknown): ExternalLocation {
  const source = value as WireExternalLocation;
  return {
    uri: source.uri,
    sheet: source.sheet ?? undefined,
    row: source.row ?? undefined,
    column: source.column ?? undefined,
    path: source.path ?? [],
  };
}

function compareRegisteredEntries(left: ConfigRegistryEntry, right: ConfigRegistryEntry): number {
  return right.registeredAt.localeCompare(left.registeredAt);
}

function compareActivations(left: ConfigActivationRecord, right: ConfigActivationRecord): number {
  return right.generation - left.generation;
}

function configDraftPayload(command: ConfigDraftCommand): DaemonUiApi["configDraftCommand"] {
  return {
    base_entry_id: command.baseEntryId,
    base_content_hash: command.baseContentHash,
    base_generation: command.baseGeneration,
    candidate_id: command.candidateId,
    updates: command.updates.map(
      configParameterUpdatePayload,
    ) as DaemonUiApi["configDraftCommand"]["updates"],
  };
}

function configDraftRegistrationPayload(
  command: ConfigDraftRegistrationCommand,
): DaemonUiApi["configDraftRegistrationCommand"] {
  return {
    draft: configDraftPayload(command.draft),
    expected_result_content_hash: command.expectedResultContentHash,
    entry_id: command.entryId,
    registered_by: command.registeredBy,
    note: command.note ?? "",
  };
}

function configParameterUpdatePayload(
  update: ConfigParameterUpdate,
): DaemonUiApi["configDraftCommand"]["updates"][number] {
  switch (update.kind) {
    case "replace_parameter":
      return {
        kind: update.kind,
        value: storedParameterValuePayload(update.value),
      };
    case "update_parameter_rows":
      return {
        kind: update.kind,
        parameter_id: update.parameterId,
        key: atomRecordPayload(update.key),
        values: atomRecordPayload(update.values),
      };
    case "insert_parameter_rows":
      return {
        kind: update.kind,
        parameter_id: update.parameterId,
        rows: update.rows.map(atomRecordPayload) as [
          Record<string, ReturnType<typeof atomPayload>>,
          ...Record<string, ReturnType<typeof atomPayload>>[],
        ],
      };
    case "delete_parameter_rows":
      return {
        kind: update.kind,
        parameter_id: update.parameterId,
        key: atomRecordPayload(update.key),
      };
  }
}

function storedParameterValuePayload(
  value: StoredParameterValue,
): Extract<DaemonUiApi["configDraftCommand"]["updates"][number], { value: unknown }>["value"] {
  const common = {
    id: value.id,
    metadata: value.metadata,
  };
  if (value.shape === "scalar") {
    return { ...common, shape: value.shape, value: atomPayload(value.value) };
  }
  if (value.shape === "series") {
    return {
      ...common,
      shape: value.shape,
      items: value.items.map(atomPayload),
    };
  }
  return {
    ...common,
    shape: value.shape,
    rows: value.rows.map(atomRecordPayload),
  };
}

function atomRecordPayload(
  values: Record<string, ParameterAtom>,
): Record<string, WireParameterAtom> {
  return Object.fromEntries(
    Object.entries(values).map(([key, value]) => [key, atomPayload(value)]),
  );
}

function atomPayload(value: ParameterAtom): WireParameterAtom {
  if (
    value === null ||
    typeof value === "boolean" ||
    typeof value === "number" ||
    typeof value === "string"
  ) {
    return value;
  }
  if ("value" in value) return { value: value.value, unit: value.unit };
  return {
    id: value.id,
    ...(value.kind ? { kind: value.kind } : {}),
    metadata: value.metadata,
  };
}

function normalizeParameterDelta(source: WireParameterDelta): ParameterValueDelta {
  return {
    parameterId: source.parameter_id,
    before: normalizeStoredParameterValue(source.before),
    after: normalizeStoredParameterValue(source.after),
  };
}

function normalizeProblem(source: WireProblem): ConfigProblem {
  return {
    code: source.code,
    impact: source.impact,
    category: source.category,
    phase: source.phase,
    message: source.message,
    location: source.location ? normalizeProblemLocation(source.location) : undefined,
    details: metadata(source.details),
  };
}

function normalizeProblemLocation(
  source: NonNullable<WireProblem["location"]>,
): ConfigProblemLocation {
  return {
    kind: source.kind!,
    root: "root" in source ? source.root : undefined,
    path: "path" in source ? (source.path ?? []) : [],
  };
}

function commandPayload(command: ConfigCommand): {
  operator: string;
  note: string;
  expected_generation: number;
} {
  return {
    operator: command.operator,
    note: command.note ?? "",
    expected_generation: command.expectedGeneration,
  };
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

function metadata(value: unknown): JsonObject {
  return (value ?? {}) as JsonObject;
}

import { request } from "./api";
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
  JsonValue,
  ParameterAtom,
  ParameterCatalog,
  ParameterDefinition,
  ParameterEntity,
  ParameterValueDelta,
  ParameterScalarType,
  ParameterSnapshot,
  ParameterTableColumn,
  ParameterValueType,
  StoredParameterValue,
  SystemSpec,
  Topology,
} from "./config-types";

const CONFIG_API = "/api/v1/config-registry";

export async function getConfigRegistry(
  signal?: AbortSignal,
): Promise<ConfigRegistryOverview> {
  return normalizeConfigRegistryOverview(await request(CONFIG_API, signal));
}

export async function getConfigRegistryEntry(
  entryId: string,
  signal?: AbortSignal,
): Promise<ConfigRegistryEntryDetail> {
  const envelope = object(
    await request(
      `${CONFIG_API}/entries/${encodeURIComponent(entryId)}`,
      signal,
    ),
    "config entry view",
  );
  literal(
    envelope.schema_version,
    "scopecat.config_entry_view.v1",
    "config entry view schema",
  );
  const config = normalizeConfigProfileSnapshot(envelope.config);
  return {
    entry: normalizeEntry(envelope.entry),
    config,
    summary: summarizeConfigSnapshot(config),
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

export async function previewConfigDraft(
  command: ConfigDraftCommand,
): Promise<ConfigDraftPreview> {
  return normalizeConfigDraftPreview(
    await request(
      `${CONFIG_API}/drafts/preview`,
      undefined,
      jsonRequest(configDraftPayload(command)),
    ),
  );
}

export async function registerConfigDraft(
  command: ConfigDraftRegistrationCommand,
): Promise<ConfigDraftRegistrationReceipt> {
  const source = object(
    await request(
      `${CONFIG_API}/drafts/register`,
      undefined,
      jsonRequest(configDraftRegistrationPayload(command)),
    ),
    "config draft registration receipt",
  );
  literal(
    source.schema_version,
    "scopecat.config_draft_registration_receipt.v1",
    "config draft registration receipt schema",
  );
  return {
    entry: normalizeEntry(source.entry),
    resultContentHash: text(
      source.result_content_hash,
      "config draft registration result hash",
    ),
    deltas: list(source.deltas, "config draft registration deltas").map(
      normalizeParameterDelta,
    ),
  };
}

export async function setConfigDraftDefault(
  command: ConfigDraftDefaultCommand,
): Promise<ConfigDraftDefaultReceipt> {
  const payload: JsonObject = {
    schema_version: "scopecat.config_draft_default_command.v1",
    registration: configDraftRegistrationPayload(command.registration),
    operator: command.operator,
  };
  if (command.activationNote !== undefined) {
    payload.activation_note = command.activationNote;
  }
  const source = object(
    await request(
      `${CONFIG_API}/drafts/set-default`,
      undefined,
      jsonRequest(payload),
    ),
    "config draft default receipt",
  );
  literal(
    source.schema_version,
    "scopecat.config_draft_default_receipt.v1",
    "config draft default receipt schema",
  );
  return {
    entry: normalizeEntry(source.entry),
    resultContentHash: text(
      source.result_content_hash,
      "config draft default result hash",
    ),
    deltas: list(source.deltas, "config draft default deltas").map(
      normalizeParameterDelta,
    ),
    activeState: normalizeActiveState(source.active_state),
    activation: normalizeActivation(source.activation),
  };
}

export function normalizeConfigDraftPreview(
  value: unknown,
): ConfigDraftPreview {
  const source = object(value, "config draft preview");
  literal(
    source.schema_version,
    "scopecat.config_draft_preview.v1",
    "config draft preview schema",
  );
  const valid = requiredBoolean(source.valid, "config draft preview valid");
  const config =
    source.config === null || source.config === undefined
      ? undefined
      : normalizeConfigProfileSnapshot(source.config);
  const resultContentHash = optionalText(source.result_content_hash);
  if (valid && (!config || !resultContentHash)) {
    throw new Error("valid config draft preview must include its candidate.");
  }
  if (!valid && (config || resultContentHash)) {
    throw new Error("invalid config draft preview cannot include a candidate.");
  }
  return {
    valid,
    baseEntry: normalizeEntry(source.base_entry),
    baseGeneration: integer(
      source.base_generation,
      "config draft base generation",
    ),
    baseContentHash: text(
      source.base_content_hash,
      "config draft base content hash",
    ),
    config,
    resultContentHash,
    deltas: list(source.deltas ?? [], "config draft deltas").map(
      normalizeParameterDelta,
    ),
    problems: list(source.problems ?? [], "config draft problems").map(
      normalizeProblem,
    ),
  };
}

export function normalizeConfigRegistryOverview(
  value: unknown,
): ConfigRegistryOverview {
  const envelope = object(value, "config registry view");
  literal(
    envelope.schema_version,
    "scopecat.config_registry_view.v1",
    "config registry view schema",
  );
  const entries = list(envelope.entries, "config registry entries")
    .map(normalizeEntry)
    .sort(compareRegisteredEntries);
  if (envelope.active_state === null || envelope.active_state === undefined) {
    return { active: undefined, entries, history: [] };
  }
  const activeState = object(envelope.active_state, "active config state");
  const active = normalizeActiveState(activeState);
  const history = list(
    activeState.history,
    "config activation history",
  )
    .map(normalizeActivation)
    .sort(compareActivations);
  return {
    active,
    entries,
    history,
  };
}

export function normalizeConfigProfileSnapshot(
  value: unknown,
): ConfigProfileSnapshot {
  const source = object(value, "config snapshot");
  literal(
    source.schema_version,
    "scopecat.config_profile_snapshot.v3",
    "config snapshot schema",
  );
  return {
    id: text(source.id, "config snapshot id"),
    system: normalizeSystem(source.system),
    environment: normalizeEnvironment(source.environment),
    parameterSnapshot: normalizeParameterSnapshot(source.parameter_snapshot),
    raw: source as JsonObject,
  };
}

export function summarizeConfigSnapshot(
  config: ConfigProfileSnapshot,
): ConfigSnapshotSummary {
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
  const schemaVersion = optionalText(profile.schema_version);
  if (schemaVersion === "scopecat.config_profile.v2") {
    throw new Error(
      "This split config_profile.v2 file must be loaded by Python before importing its config_profile_snapshot.v3 result.",
    );
  }
  if (schemaVersion !== "scopecat.config_profile_snapshot.v3") {
    throw new Error(
      `Unsupported config snapshot schema: ${schemaVersion ?? "missing schema_version"}.`,
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
  return profile as JsonObject;
}

function normalizeEntry(value: unknown): ConfigRegistryEntry {
  const source = object(value, "config registry entry");
  literal(
    source.schema_version,
    "scopecat.config.registry_entry.v7",
    "config registry entry schema",
  );
  return {
    id: text(source.id, "config registry entry id"),
    contentHash: text(source.content_hash, "config registry content hash"),
    configRef: text(source.config_ref, "config registry ref"),
    registeredBy: text(source.registered_by, "config registry operator"),
    registeredAt: text(source.registered_at, "config registry timestamp"),
    note: optionalText(source.note),
    source: normalizeRegistrySource(source.source),
  };
}

function normalizeRegistrySource(value: unknown): ConfigRegistrySource {
  const source = object(value, "config registry source");
  const kind = text(source.kind, "config registry source kind");
  if (kind === "direct_config_profile") {
    return { kind, proposalIds: [] };
  }
  if (kind === "candidate_config") {
    return {
      kind,
      runId: text(source.run_id, "candidate source run id"),
      proposalIds: list(
        source.proposal_evidence,
        "candidate proposal evidence",
      ).map((item) =>
        text(
          object(item, "candidate proposal evidence").proposal_id,
          "candidate proposal id",
        ),
      ),
      baseContentHash: text(
        source.base_config_content_hash,
        "candidate base content hash",
      ),
    };
  }
  if (kind === "manual_parameter_updates") {
    return {
      kind,
      proposalIds: [],
      baseEntryId: text(source.base_entry_id, "manual edit base entry id"),
      baseContentHash: text(
        source.base_config_content_hash,
        "manual edit base content hash",
      ),
      baseGeneration: integer(
        source.base_registry_generation,
        "manual edit base generation",
      ),
    };
  }
  throw new Error(`Unsupported config registry source: ${kind}.`);
}

function normalizeActivation(value: unknown): ConfigActivationRecord {
  const source = object(value, "config activation record");
  literal(
    source.schema_version,
    "scopecat.config.registry_activation_record.v2",
    "config activation record schema",
  );
  const action = text(source.action, "config activation action");
  if (action !== "activation" && action !== "rollback") {
    throw new Error(`Unsupported config activation action: ${action}.`);
  }
  return {
    id: text(source.id, "config activation id"),
    generation: integer(source.generation, "config activation generation"),
    action,
    entryId: text(source.entry_id, "config activation entry id"),
    entryContentHash: text(
      source.entry_content_hash,
      "config activation content hash",
    ),
    previousEntryId: optionalText(source.previous_entry_id),
    operator: text(source.operator, "config activation operator"),
    note: optionalText(source.note),
    recordedAt: text(source.recorded_at, "config activation timestamp"),
  };
}

function normalizeActiveState(value: unknown): ActiveConfigState {
  const source = object(value, "active config state");
  literal(
    source.schema_version,
    "scopecat.config.registry_active_state.v2",
    "active config state schema",
  );
  return {
    generation: integer(source.generation, "active generation"),
    entryId: text(source.active_entry_id, "active entry id"),
    contentHash: text(
      source.active_entry_content_hash,
      "active content hash",
    ),
    updatedAt: optionalText(source.updated_at),
  };
}

function normalizeSystem(value: unknown): SystemSpec {
  const source = object(value, "system spec");
  literal(
    source.schema_version,
    "scopecat.system_spec.v4",
    "system spec schema",
  );
  const instruments = object(
    source.instrument_registry,
    "instrument registry",
  );
  const routing = object(source.routing, "routing graph");
  const domainTarget =
    source.domain_target === null || source.domain_target === undefined
      ? undefined
      : object(source.domain_target, "domain target");
  return {
    id: text(source.id, "system id"),
    primaryEntityId: text(
      source.primary_entity_id,
      "system primary entity id",
    ),
    topology: normalizeTopology(source.topology),
    instruments: list(instruments.instruments, "instruments").map((item) => {
      const instrument = object(item, "instrument");
      return {
        id: text(instrument.id, "instrument id"),
        kind: text(instrument.kind, "instrument kind"),
      };
    }),
    routing: list(routing.bindings ?? [], "routing bindings").map((item) => {
      const binding = object(item, "routing binding");
      return {
        instrumentId: text(binding.instrument_id, "routing instrument id"),
        capability: text(binding.capability, "routing capability"),
        entityId: optionalText(binding.entity_id),
        channelId: optionalText(binding.channel_id),
        metadata: metadata(binding.metadata),
      };
    }),
    domainTarget: domainTarget
      ? {
          id: text(domainTarget.id, "domain target id"),
          kind: text(domainTarget.kind, "domain target kind"),
          instrumentIds: stringList(
            domainTarget.instrument_ids,
            "domain target instruments",
          ),
        }
      : undefined,
    parameterCatalog: normalizeParameterCatalog(source.parameter_catalog),
  };
}

function normalizeTopology(value: unknown): Topology {
  const source = object(value, "topology");
  return {
    entities: list(source.entities ?? [], "topology entities").map(
      normalizeEntity,
    ),
    devices: list(source.devices, "topology devices").map((item) => {
      const device = object(item, "topology device");
      return {
        id: text(device.id, "device id"),
        kind: text(device.kind, "device kind"),
        channels: stringList(device.channels ?? [], "device channels"),
      };
    }),
    links: list(source.links ?? [], "topology links").map((item) => {
      const link = object(item, "topology link");
      return {
        id: text(link.id, "link id"),
        endpoints: stringList(link.endpoints, "link endpoints"),
        kind: text(link.kind, "link kind"),
      };
    }),
    lines: list(source.lines ?? [], "topology lines").map((item) => {
      const line = object(item, "topology line");
      return {
        id: text(line.id, "line id"),
        kind: text(line.kind, "line kind"),
        signal: optionalText(line.signal),
        endpoints: stringList(line.endpoints ?? [], "line endpoints"),
        metadata: metadata(line.metadata),
      };
    }),
    channels: list(source.channels ?? [], "topology channels").map((item) => {
      const channel = object(item, "topology channel");
      return {
        id: text(channel.id, "channel id"),
        kind: text(channel.kind, "channel kind"),
        deviceId: optionalText(channel.device_id),
        direction: optionalText(channel.direction),
        signal: optionalText(channel.signal),
        port: optionalText(channel.port),
        lineId: optionalText(channel.line_id),
        groupIds: stringList(channel.group_ids ?? [], "channel groups"),
        metadata: metadata(channel.metadata),
      };
    }),
    groups: list(source.groups ?? [], "topology groups").map((item) => {
      const group = object(item, "topology group");
      return {
        id: text(group.id, "group id"),
        kind: text(group.kind, "group kind"),
        members: stringList(group.members ?? [], "group members"),
        metadata: metadata(group.metadata),
      };
    }),
  };
}

function normalizeEnvironment(value: unknown): EnvironmentSpec {
  const source = object(value, "environment spec");
  literal(
    source.schema_version,
    "scopecat.environment_spec.v2",
    "environment spec schema",
  );
  const profile = object(source.connection_profile, "connection profile");
  return {
    id: text(source.id, "environment id"),
    connections: list(profile.connections ?? [], "connections").map((item) => {
      const connection = object(item, "connection");
      return {
        id: text(connection.id, "connection id"),
        instrumentId: text(
          connection.instrument_id,
          "connection instrument id",
        ),
        kind: text(connection.kind, "connection kind"),
        resourceHint: optionalText(connection.resource_hint),
      };
    }),
  };
}

function normalizeParameterCatalog(value: unknown): ParameterCatalog {
  const source = object(value, "parameter catalog");
  literal(
    source.schema_version,
    "scopecat.parameter_catalog.v4",
    "parameter catalog schema",
  );
  return {
    id: text(source.id, "parameter catalog id"),
    definitions: list(
      source.definitions ?? [],
      "parameter definitions",
    ).map(normalizeParameterDefinition),
    metadata: metadata(source.metadata),
  };
}

function normalizeParameterDefinition(value: unknown): ParameterDefinition {
  const source = object(value, "parameter definition");
  return {
    id: text(source.id, "parameter definition id"),
    valueType: normalizeValueType(source.value_type),
    description: optionalText(source.description),
    metadata: metadata(source.metadata),
  };
}

function normalizeValueType(value: unknown): ParameterValueType {
  const source = object(value, "parameter value type");
  const shape = text(source.shape, "parameter value shape");
  if (shape === "scalar") {
    return { shape, atom: normalizeScalarType(source.atom) };
  }
  if (shape === "series") {
    return {
      shape,
      itemType: normalizeScalarType(source.item_type),
      minLength: optionalInteger(source.min_length) ?? 0,
      maxLength: optionalInteger(source.max_length),
    };
  }
  if (shape === "table") {
    return {
      shape,
      columns: list(source.columns, "parameter table columns").map(
        normalizeTableColumn,
      ),
      primaryKey: stringList(
        source.primary_key ?? [],
        "parameter table primary key",
      ),
      minRows: optionalInteger(source.min_rows) ?? 0,
      maxRows: optionalInteger(source.max_rows),
    };
  }
  throw new Error(`Unsupported parameter value shape: ${shape}.`);
}

function normalizeTableColumn(value: unknown): ParameterTableColumn {
  const source = object(value, "parameter table column");
  return {
    id: text(source.id, "parameter table column id"),
    valueType: normalizeScalarType(source.value_type),
    required: optionalBoolean(source.required) ?? true,
  };
}

function normalizeScalarType(value: unknown): ParameterScalarType {
  const source = object(value, "parameter scalar type");
  const type = text(source.type, "parameter scalar atom type");
  const nullable = optionalBoolean(source.nullable) ?? false;
  if (type === "bool") return { type, nullable };
  if (type === "int") {
    return {
      type,
      nullable,
      minimum: optionalInteger(source.minimum),
      maximum: optionalInteger(source.maximum),
    };
  }
  if (type === "float") {
    return {
      type,
      nullable,
      minimum: optionalNumber(source.minimum),
      maximum: optionalNumber(source.maximum),
      finite: optionalBoolean(source.finite) ?? true,
    };
  }
  if (type === "string") {
    return {
      type,
      nullable,
      minLength: optionalInteger(source.min_length) ?? 0,
      maxLength: optionalInteger(source.max_length),
      pattern: optionalText(source.pattern),
      choices:
        source.choices === null || source.choices === undefined
          ? undefined
          : stringList(source.choices, "parameter string choices"),
    };
  }
  if (type === "quantity") {
    return {
      type,
      nullable,
      dimension: optionalText(source.dimension),
      unit: optionalText(source.unit),
      minimum: optionalNumber(source.minimum),
      maximum: optionalNumber(source.maximum),
      finite: optionalBoolean(source.finite) ?? true,
    };
  }
  if (type === "entity") {
    return {
      type,
      nullable,
      entityKind: optionalText(source.entity_kind),
    };
  }
  throw new Error(`Unsupported persisted parameter atom type: ${type}.`);
}

function normalizeParameterSnapshot(value: unknown): ParameterSnapshot {
  const source = object(value, "parameter snapshot");
  literal(
    source.schema_version,
    "scopecat.parameter_snapshot.v2",
    "parameter snapshot schema",
  );
  return {
    id: text(source.id, "parameter snapshot id"),
    values: list(source.values ?? [], "parameter values").map(
      normalizeStoredParameterValue,
    ),
    metadata: metadata(source.metadata),
  };
}

function normalizeStoredParameterValue(value: unknown): StoredParameterValue {
  const source = object(value, "stored parameter value");
  const shape = text(source.shape, "stored parameter shape");
  const common = {
    id: text(source.id, "stored parameter id"),
    sourceLocation: normalizeOptionalLocation(source.source_location),
    metadata: metadata(source.metadata),
  };
  if (shape === "scalar") {
    return {
      ...common,
      shape,
      value: normalizeParameterAtom(source.value),
    };
  }
  if (shape === "series") {
    return {
      ...common,
      shape,
      items: list(source.items ?? [], "parameter series items").map(
        normalizeParameterAtom,
      ),
      itemLocations: list(
        source.item_locations ?? [],
        "parameter series locations",
      ).map(normalizeLocation),
    };
  }
  if (shape === "table") {
    return {
      ...common,
      shape,
      rows: list(source.rows ?? [], "parameter table rows").map((rowValue) => {
        const row = object(rowValue, "parameter table row");
        return Object.fromEntries(
          Object.entries(row).map(([column, cell]) => [
            column,
            normalizeParameterAtom(cell),
          ]),
        );
      }),
      rowLocations: list(
        source.row_locations ?? [],
        "parameter table locations",
      ).map(normalizeLocation),
    };
  }
  throw new Error(`Unsupported stored parameter shape: ${shape}.`);
}

function normalizeParameterAtom(value: unknown): ParameterAtom {
  if (
    value === null ||
    typeof value === "boolean" ||
    typeof value === "string"
  ) {
    return value;
  }
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const source = object(value, "parameter atom");
  if ("value" in source && "unit" in source) {
    return {
      value: finiteNumber(source.value, "parameter quantity value"),
      unit: text(source.unit, "parameter quantity unit"),
    };
  }
  if ("id" in source) return normalizeEntity(source);
  throw new Error("Unsupported persisted parameter atom.");
}

function normalizeEntity(value: unknown): ParameterEntity {
  const source = object(value, "entity reference");
  return {
    id: text(source.id, "entity id"),
    kind: optionalText(source.kind),
    metadata: metadata(source.metadata),
  };
}

function normalizeOptionalLocation(
  value: unknown,
): ExternalLocation | undefined {
  return value === null || value === undefined
    ? undefined
    : normalizeLocation(value);
}

function normalizeLocation(value: unknown): ExternalLocation {
  const source = object(value, "external location");
  literal(source.kind, "external", "external location kind");
  const column = source.column;
  if (
    column !== null &&
    column !== undefined &&
    typeof column !== "string" &&
    !(typeof column === "number" && Number.isInteger(column))
  ) {
    throw new Error("external location column must be a string or integer.");
  }
  return {
    uri: text(source.uri, "external location uri"),
    sheet: optionalText(source.sheet),
    row: optionalInteger(source.row),
    column: column ?? undefined,
    path: list(source.path ?? [], "external location path").map((item) => {
      if (typeof item === "string") return item;
      return integer(item, "external location path index");
    }),
  };
}

function compareRegisteredEntries(
  left: ConfigRegistryEntry,
  right: ConfigRegistryEntry,
): number {
  return right.registeredAt.localeCompare(left.registeredAt);
}

function compareActivations(
  left: ConfigActivationRecord,
  right: ConfigActivationRecord,
): number {
  return right.generation - left.generation;
}

function configDraftPayload(command: ConfigDraftCommand): JsonObject {
  return {
    schema_version: "scopecat.config_draft_command.v1",
    base_entry_id: command.baseEntryId,
    base_content_hash: command.baseContentHash,
    base_generation: command.baseGeneration,
    candidate_id: command.candidateId,
    updates: command.updates.map(configParameterUpdatePayload),
  };
}

function configDraftRegistrationPayload(
  command: ConfigDraftRegistrationCommand,
): JsonObject {
  return {
    schema_version: "scopecat.config_draft_registration_command.v1",
    draft: configDraftPayload(command.draft),
    expected_result_content_hash: command.expectedResultContentHash,
    entry_id: command.entryId,
    registered_by: command.registeredBy,
    note: command.note ?? "",
  };
}

function configParameterUpdatePayload(
  update: ConfigParameterUpdate,
): JsonObject {
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
        rows: update.rows.map(atomRecordPayload),
      };
    case "delete_parameter_rows":
      return {
        kind: update.kind,
        parameter_id: update.parameterId,
        key: atomRecordPayload(update.key),
      };
  }
}

function storedParameterValuePayload(value: StoredParameterValue): JsonObject {
  const common: JsonObject = {
    id: value.id,
    shape: value.shape,
    metadata: value.metadata,
  };
  if (value.shape === "scalar") {
    return { ...common, value: atomPayload(value.value) };
  }
  if (value.shape === "series") {
    return {
      ...common,
      items: value.items.map(atomPayload),
    };
  }
  return {
    ...common,
    rows: value.rows.map(atomRecordPayload),
  };
}

function atomRecordPayload(
  values: Record<string, ParameterAtom>,
): JsonObject {
  return Object.fromEntries(
    Object.entries(values).map(([key, value]) => [key, atomPayload(value)]),
  );
}

function atomPayload(value: ParameterAtom): JsonValue {
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

function normalizeParameterDelta(value: unknown): ParameterValueDelta {
  const source = object(value, "parameter value delta");
  return {
    parameterId: text(source.parameter_id, "parameter delta id"),
    before: normalizeStoredParameterValue(source.before),
    after: normalizeStoredParameterValue(source.after),
  };
}

function normalizeProblem(value: unknown): ConfigProblem {
  const source = object(value, "config draft problem");
  literal(
    source.schema_version,
    "scopecat.problem.v1",
    "config draft problem schema",
  );
  const impact = text(source.impact, "config draft problem impact");
  if (impact !== "advisory" && impact !== "blocking") {
    throw new Error(`Unsupported config draft problem impact: ${impact}.`);
  }
  return {
    code: text(source.code, "config draft problem code"),
    impact,
    category: text(source.category, "config draft problem category"),
    phase: text(source.phase, "config draft problem phase"),
    message: text(source.message, "config draft problem message"),
    location:
      source.location === null || source.location === undefined
        ? undefined
        : normalizeProblemLocation(source.location),
    details: metadata(source.details),
  };
}

function normalizeProblemLocation(value: unknown): ConfigProblemLocation {
  const source = object(value, "config draft problem location");
  return {
    kind: text(source.kind, "config draft problem location kind"),
    root: optionalText(source.root),
    path: list(source.path ?? [], "config draft problem location path").map(
      (item) =>
        typeof item === "string"
          ? text(item, "config draft problem path segment")
          : integer(item, "config draft problem path index"),
    ),
  };
}

function commandPayload(command: ConfigCommand): JsonObject {
  return {
    operator: command.operator,
    note: command.note ?? "",
    expected_generation: command.expectedGeneration,
  };
}

function jsonRequest(body: JsonObject): RequestInit {
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

function list(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array.`);
  return value;
}

function stringList(value: unknown, label: string): string[] {
  return list(value, label).map((item) => text(item, `${label} item`));
}

function text(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${label} must be non-empty text.`);
  }
  return value;
}

function optionalText(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function finiteNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} must be a finite number.`);
  }
  return value;
}

function optionalNumber(value: unknown): number | undefined {
  return value === null || value === undefined
    ? undefined
    : finiteNumber(value, "numeric field");
}

function integer(value: unknown, label: string): number {
  const selected = finiteNumber(value, label);
  if (!Number.isInteger(selected)) throw new Error(`${label} must be an integer.`);
  return selected;
}

function optionalInteger(value: unknown): number | undefined {
  return value === null || value === undefined
    ? undefined
    : integer(value, "integer field");
}

function optionalBoolean(value: unknown): boolean | undefined {
  if (value === null || value === undefined) return undefined;
  if (typeof value !== "boolean") throw new Error("boolean field must be a bool.");
  return value;
}

function requiredBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${label} must be a bool.`);
  return value;
}

function literal(value: unknown, expected: string, label: string): void {
  if (value !== expected) {
    throw new Error(`${label} must be ${expected}.`);
  }
}

function metadata(value: unknown): JsonObject {
  return (value === null || value === undefined
    ? {}
    : object(value, "metadata")) as JsonObject;
}

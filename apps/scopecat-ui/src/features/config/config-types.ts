export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export type JsonObject = { [key: string]: JsonValue };

export interface ParameterQuantity {
  value: number;
  unit: string;
}

export interface ParameterEntity {
  id: string;
  kind?: string;
  metadata: JsonObject;
}

export type ParameterAtom = null | boolean | number | string | ParameterQuantity | ParameterEntity;

interface ScalarTypeBase {
  nullable: boolean;
}

export interface BoolScalarType extends ScalarTypeBase {
  type: "bool";
}

export interface IntScalarType extends ScalarTypeBase {
  type: "int";
  minimum?: number;
  maximum?: number;
}

export interface FloatScalarType extends ScalarTypeBase {
  type: "float";
  minimum?: number;
  maximum?: number;
  finite: boolean;
}

export interface StringScalarType extends ScalarTypeBase {
  type: "string";
  minLength: number;
  maxLength?: number;
  pattern?: string;
  choices?: string[];
}

export interface QuantityScalarType extends ScalarTypeBase {
  type: "quantity";
  dimension?: string;
  unit?: string;
  minimum?: number;
  maximum?: number;
  finite: boolean;
}

export interface EntityScalarType extends ScalarTypeBase {
  type: "entity";
  entityKind?: string;
}

export type ParameterScalarType =
  | BoolScalarType
  | IntScalarType
  | FloatScalarType
  | StringScalarType
  | QuantityScalarType
  | EntityScalarType;

export interface ScalarParameterType {
  shape: "scalar";
  atom: ParameterScalarType;
}

export interface SeriesParameterType {
  shape: "series";
  itemType: ParameterScalarType;
  minLength: number;
  maxLength?: number;
}

export interface ParameterTableColumn {
  id: string;
  valueType: ParameterScalarType;
  required: boolean;
}

export interface TableParameterType {
  shape: "table";
  columns: ParameterTableColumn[];
  primaryKey: string[];
  minRows: number;
  maxRows?: number;
}

export type ParameterValueType = ScalarParameterType | SeriesParameterType | TableParameterType;

export interface ParameterDefinition {
  id: string;
  valueType: ParameterValueType;
  description?: string;
  metadata: JsonObject;
}

export interface ParameterCatalog {
  id: string;
  definitions: ParameterDefinition[];
  metadata: JsonObject;
}

export interface ExternalLocation {
  uri: string;
  sheet?: string;
  row?: number;
  column?: number | string;
  path: Array<number | string>;
}

interface StoredParameterValueBase {
  id: string;
  sourceLocation?: ExternalLocation;
  metadata: JsonObject;
}

export interface ScalarParameterValue extends StoredParameterValueBase {
  shape: "scalar";
  value: ParameterAtom;
}

export interface SeriesParameterValue extends StoredParameterValueBase {
  shape: "series";
  items: ParameterAtom[];
  itemLocations: ExternalLocation[];
}

export interface TableParameterValue extends StoredParameterValueBase {
  shape: "table";
  rows: Array<Record<string, ParameterAtom>>;
  rowLocations: ExternalLocation[];
}

export type StoredParameterValue =
  | ScalarParameterValue
  | SeriesParameterValue
  | TableParameterValue;

export interface ParameterSnapshot {
  id: string;
  values: StoredParameterValue[];
  metadata: JsonObject;
}

export interface Device {
  id: string;
  kind: string;
  channels: string[];
}

export interface Link {
  id: string;
  endpoints: string[];
  kind: string;
}

export interface TopologyLine {
  id: string;
  kind: string;
  signal?: string;
  endpoints: string[];
  metadata: JsonObject;
}

export interface SharedResourceGroup {
  id: string;
  kind: string;
  members: string[];
  metadata: JsonObject;
}

export interface Channel {
  id: string;
  kind: string;
  deviceId?: string;
  direction?: string;
  signal?: string;
  port?: string;
  lineId?: string;
  groupIds: string[];
  metadata: JsonObject;
}

export interface Topology {
  entities: ParameterEntity[];
  devices: Device[];
  links: Link[];
  lines: TopologyLine[];
  channels: Channel[];
  groups: SharedResourceGroup[];
}

export interface InstrumentSpec {
  id: string;
  kind: string;
}

export interface RoutingEndpointBinding {
  instrumentId: string;
  capability: string;
  entityId?: string;
  channelId?: string;
  metadata: JsonObject;
}

export interface DomainTargetBinding {
  id: string;
  kind: string;
  instrumentIds: string[];
}

export interface SystemSpec {
  id: string;
  primaryEntityId: string;
  topology: Topology;
  instruments: InstrumentSpec[];
  routing: RoutingEndpointBinding[];
  domainTarget?: DomainTargetBinding;
  parameterCatalog: ParameterCatalog;
}

export interface ConnectionResource {
  id: string;
  instrumentId: string;
  kind: string;
  resourceHint?: string;
}

export interface EnvironmentSpec {
  id: string;
  connections: ConnectionResource[];
}

export interface ConfigProfileSnapshot {
  id: string;
  system: SystemSpec;
  environment: EnvironmentSpec;
  parameterSnapshot: ParameterSnapshot;
  /** Exact daemon wire document retained for the Advanced raw view. */
  raw: JsonObject;
}

export interface ConfigSnapshotSummary {
  id: string;
  primaryEntityId: string;
  parameterCount: number;
  instrumentCount: number;
  connectionCount: number;
}

export interface ConfigRegistrySource {
  kind: "direct_config_profile" | "candidate_config" | "manual_parameter_updates";
  runId?: string;
  proposalIds: string[];
  baseEntryId?: string;
  baseContentHash?: string;
  baseGeneration?: number;
}

export interface ConfigRegistryEntry {
  id: string;
  contentHash: string;
  configRef: string;
  registeredBy: string;
  registeredAt: string;
  note?: string;
  source: ConfigRegistrySource;
}

export interface ConfigActivationRecord {
  id: string;
  generation: number;
  action: "activation" | "rollback";
  entryId: string;
  entryContentHash: string;
  previousEntryId?: string;
  operator: string;
  note?: string;
  recordedAt: string;
}

export interface ActiveConfigState {
  generation: number;
  entryId: string;
  contentHash: string;
  updatedAt?: string;
}

export interface ConfigRegistryOverview {
  active?: ActiveConfigState;
  entries: ConfigRegistryEntry[];
  history: ConfigActivationRecord[];
}

export interface ConfigRegistryEntryDetail {
  entry: ConfigRegistryEntry;
  config: ConfigProfileSnapshot;
  summary: ConfigSnapshotSummary;
}

export interface ConfigCommand {
  operator: string;
  note?: string;
  expectedGeneration: number;
}

export interface ImportConfigCommand {
  entryId: string;
  registeredBy: string;
  note?: string;
  config: JsonObject;
}

export type ConfigParameterUpdate =
  | {
      kind: "replace_parameter";
      value: StoredParameterValue;
    }
  | {
      kind: "update_parameter_rows";
      parameterId: string;
      key: Record<string, ParameterAtom>;
      values: Record<string, ParameterAtom>;
    }
  | {
      kind: "insert_parameter_rows";
      parameterId: string;
      rows: Array<Record<string, ParameterAtom>>;
    }
  | {
      kind: "delete_parameter_rows";
      parameterId: string;
      key: Record<string, ParameterAtom>;
    };

export interface ConfigDraftCommand {
  baseEntryId: string;
  baseContentHash: string;
  baseGeneration: number;
  candidateId: string;
  updates: ConfigParameterUpdate[];
}

export interface ConfigProblemLocation {
  kind: string;
  root?: string;
  path: Array<string | number>;
}

export interface ConfigProblem {
  code: string;
  impact: "advisory" | "blocking";
  category: string;
  phase: string;
  message: string;
  location?: ConfigProblemLocation;
  details: JsonObject;
}

export interface ParameterValueDelta {
  parameterId: string;
  before: StoredParameterValue;
  after: StoredParameterValue;
}

export interface ConfigDraftPreview {
  valid: boolean;
  baseEntry: ConfigRegistryEntry;
  baseGeneration: number;
  baseContentHash: string;
  config?: ConfigProfileSnapshot;
  resultContentHash?: string;
  deltas: ParameterValueDelta[];
  problems: ConfigProblem[];
}

export interface ConfigDraftRegistrationCommand {
  draft: ConfigDraftCommand;
  expectedResultContentHash: string;
  entryId: string;
  registeredBy: string;
  note?: string;
}

export interface ConfigDraftRegistrationReceipt {
  entry: ConfigRegistryEntry;
  resultContentHash: string;
  deltas: ParameterValueDelta[];
}

export interface ConfigDraftDefaultCommand {
  registration: ConfigDraftRegistrationCommand;
  operator: string;
  activationNote?: string;
}

export interface ConfigDraftDefaultReceipt extends ConfigDraftRegistrationReceipt {
  activeState: ActiveConfigState;
  activation: ConfigActivationRecord;
}

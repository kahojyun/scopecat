import { ApiError, request } from "../../api";
import type {
  ConfigProfileSnapshot,
  DaemonUiApi,
  InstrumentAcquisition,
  InstrumentAcquisitionResult,
  InstrumentApplyReceipt,
  InstrumentCollectReceipt,
  InstrumentConnection,
  InstrumentConfiguredDefaultsApplyReceipt,
  InstrumentInvokeReceipt,
  InstrumentOperation,
  InstrumentSession,
  InstrumentSessionLease,
  InstrumentState,
  InstrumentStateValue,
  InstrumentView,
} from "../../api-contract";
import { setConfigDefault } from "../config/config-api";
import { safeConfigEntryId } from "../config/config-utils";

const INSTRUMENT_API = "/api/v1/instruments";
const SESSION_API = "/api/v1/instrument-sessions";

export type ActiveConfig = DaemonUiApi["activeConfig"];
export type InstrumentList = DaemonUiApi["instrumentList"];

export interface StagedInstrumentProperty {
  interfaceId: string;
  componentPath: string[];
  propertyId: string;
  value: InstrumentStateValue;
}

export interface InstrumentAcquisitionTarget {
  interfaceId: string;
  componentPath: string[];
  acquisition: InstrumentAcquisition;
}

export interface InstrumentOperationTarget {
  interfaceId: string;
  componentPath: string[];
  operation: InstrumentOperation;
}

export type InstrumentOperationArgument = NonNullable<
  DaemonUiApi["instrumentInvokeCommand"]["arguments"]
>[number];

export async function getInstruments(signal?: AbortSignal): Promise<InstrumentList> {
  return request<InstrumentList>(INSTRUMENT_API, signal);
}

export async function getInstrument(
  instrumentId: string,
  signal?: AbortSignal,
): Promise<InstrumentView> {
  return request<InstrumentView>(`${INSTRUMENT_API}/${encodeURIComponent(instrumentId)}`, signal);
}

export async function getActiveConfig(signal?: AbortSignal): Promise<ActiveConfig> {
  return request<ActiveConfig>("/api/v1/config-registry/active", signal);
}

export async function openInstrumentSession(
  instrumentId: string,
  actor: string,
  operationId = createInstrumentCommandId("open"),
): Promise<InstrumentSession> {
  return request<InstrumentSession>(
    SESSION_API,
    undefined,
    jsonRequest({
      operation_id: operationId,
      actor,
      instrument_ids: [instrumentId],
    } satisfies DaemonUiApi["instrumentSessionOpenCommand"]),
  );
}

export async function renewInstrumentSession(sessionId: string): Promise<InstrumentSessionLease> {
  return request<InstrumentSessionLease>(
    `${SESSION_API}/${encodeURIComponent(sessionId)}/heartbeat`,
    undefined,
    { method: "POST" },
  );
}

export async function readInstrumentState(
  session: InstrumentSession,
  instrumentId: string,
): Promise<InstrumentState> {
  return request<InstrumentState>(instrumentSessionPath(session.session_id, instrumentId, "state"));
}

export async function applyInstrumentState(
  session: InstrumentSession,
  instrumentId: string,
  properties: StagedInstrumentProperty[],
  commandId = createInstrumentCommandId("apply"),
): Promise<InstrumentApplyReceipt> {
  const [first, ...remaining] = properties;
  if (!first) throw new Error("Apply requires at least one staged property.");
  const assignment = (property: StagedInstrumentProperty) => ({
    resource_id: instrumentId,
    interface_id: property.interfaceId,
    component_path: property.componentPath,
    property_id: property.propertyId,
    value: property.value,
  });
  return request<InstrumentApplyReceipt>(
    instrumentSessionPath(session.session_id, instrumentId, "state/apply"),
    undefined,
    jsonRequest({
      command_id: commandId,
      instrument_id: instrumentId,
      assignments: [assignment(first), ...remaining.map(assignment)],
    } satisfies DaemonUiApi["instrumentApplyCommand"]),
  );
}

export async function applyInstrumentConfiguredDefaults(
  session: InstrumentSession,
  instrumentId: string,
  operationId = createInstrumentCommandId("configured-defaults"),
): Promise<InstrumentConfiguredDefaultsApplyReceipt> {
  return request<InstrumentConfiguredDefaultsApplyReceipt>(
    instrumentSessionPath(session.session_id, instrumentId, "configured-defaults/apply"),
    undefined,
    jsonRequest({
      operation_id: operationId,
    } satisfies DaemonUiApi["instrumentConfiguredDefaultsApplyCommand"]),
  );
}

export async function collectInstrumentAcquisition(
  session: InstrumentSession,
  instrumentId: string,
  target: InstrumentAcquisitionTarget,
  commandId = createInstrumentCommandId("collect"),
): Promise<InstrumentCollectReceipt> {
  return request<InstrumentCollectReceipt>(
    instrumentSessionPath(session.session_id, instrumentId, "collect"),
    undefined,
    jsonRequest({
      command_id: commandId,
      instrument_id: instrumentId,
      interface_id: target.interfaceId,
      component_path: target.componentPath,
      acquisition_id: target.acquisition.id,
      result_ids: [],
    } satisfies DaemonUiApi["interactiveCollectIntent"]),
  );
}

export async function invokeInstrumentOperation(
  session: InstrumentSession,
  instrumentId: string,
  target: InstrumentOperationTarget,
  arguments_: InstrumentOperationArgument[],
  commandId = createInstrumentCommandId("invoke"),
): Promise<InstrumentInvokeReceipt> {
  return request<InstrumentInvokeReceipt>(
    instrumentSessionPath(session.session_id, instrumentId, "invoke"),
    undefined,
    jsonRequest({
      command_id: commandId,
      instrument_id: instrumentId,
      resource_id: instrumentId,
      interface_id: target.interfaceId,
      component_path: target.componentPath,
      operation_id: target.operation.id,
      arguments: arguments_,
    } satisfies DaemonUiApi["instrumentInvokeCommand"]),
  );
}

export async function closeInstrumentSession(sessionId: string, keepalive = false): Promise<void> {
  await endInstrumentSession(sessionId, "close", keepalive);
}

export async function abortInstrumentSession(sessionId: string): Promise<void> {
  await endInstrumentSession(sessionId, "abort");
}

async function endInstrumentSession(
  sessionId: string,
  action: "close" | "abort",
  keepalive = false,
): Promise<void> {
  await request<DaemonUiApi["instrumentSessionEndReceipt"]>(
    `${SESSION_API}/${encodeURIComponent(sessionId)}/${action}`,
    undefined,
    { method: "POST", keepalive },
  );
}

export async function resolveInstrumentAttention(sessionId: string): Promise<void> {
  await request<DaemonUiApi["instrumentSessionEndReceipt"]>(
    `${SESSION_API}/${encodeURIComponent(sessionId)}/attention`,
    undefined,
    { method: "POST" },
  );
}

export async function publishInstrumentConnection({
  active,
  instrumentId,
  connection,
  actor,
  note,
}: {
  active: ActiveConfig;
  instrumentId: string;
  connection: InstrumentConnection;
  actor: string;
  note: string;
}): Promise<void> {
  const config = cloneConfig(active.config);
  const spec = config.system.instrument_registry.instruments.find(
    (instrument) => instrument.id === instrumentId,
  );
  if (!spec) throw new Error(`The active config no longer contains ${instrumentId}.`);
  spec.connection = connection;
  const suffix = createInstrumentCommandId("config");
  const entryId = safeConfigEntryId(`${config.id}-instrument-${instrumentId}-${suffix}`);
  config.id = entryId;
  await setConfigDefault({
    source: {
      kind: "direct_config_profile",
      config,
    },
    entry_id: entryId,
    actor,
    note,
    expected_generation: active.activation.generation,
  });
}

export function connectionSummary(connection: InstrumentView["connection"]): string {
  switch (connection.kind) {
    case "virtual":
      return "Virtual · local simulator";
    case "tcpip_socket":
      return `TCP/IP · ${connection.host}:${connection.port}`;
  }
}

export function createInstrumentCommandId(prefix: string): string {
  const random =
    typeof globalThis.crypto?.randomUUID === "function"
      ? globalThis.crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `ui-${prefix}-${random}`;
}

export function retryTransientInstrumentMutation(failureCount: number, error: unknown): boolean {
  return failureCount < 1 && error instanceof ApiError && error.status === undefined;
}

function instrumentSessionPath(
  sessionId: string,
  instrumentId: string,
  operation: "state" | "state/apply" | "configured-defaults/apply" | "invoke" | "collect",
): string {
  return (
    `${SESSION_API}/${encodeURIComponent(sessionId)}/instruments/` +
    `${encodeURIComponent(instrumentId)}/${operation}`
  );
}

export function declaredAcquisitionResults(
  acquisition: InstrumentAcquisition,
): InstrumentAcquisitionResult[] {
  return acquisition.kind === "fixed"
    ? acquisition.results
    : acquisition.cases.flatMap((candidate) => candidate.results);
}

function cloneConfig(source: ActiveConfig["config"]): ConfigProfileSnapshot {
  return JSON.parse(JSON.stringify(source)) as ConfigProfileSnapshot;
}

function jsonRequest(body: object): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

import { ApiError, request } from "../../api";
import type {
  ConfigProfileSnapshot,
  DaemonUiApi,
  InstrumentAcquisition,
  InstrumentAcquisitionResult,
  InstrumentApplyReceipt,
  InstrumentCollectReceipt,
  InstrumentConnection,
  InstrumentInvokeReceipt,
  InstrumentOperation,
  InstrumentSession,
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

export interface InstrumentAcquisitionReadiness {
  ready: boolean;
  reason?: string;
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

export async function collectInstrumentAcquisition(
  session: InstrumentSession,
  instrumentId: string,
  target: InstrumentAcquisitionTarget,
  state?: InstrumentState,
  commandId = createInstrumentCommandId("collect"),
): Promise<InstrumentCollectReceipt> {
  const plan = planInstrumentAcquisition(target, state);
  if (!plan.ready) throw new Error(plan.reason);
  return request<InstrumentCollectReceipt>(
    instrumentSessionPath(session.session_id, instrumentId, "collect"),
    undefined,
    jsonRequest({
      command_id: commandId,
      instrument_id: instrumentId,
      point_index: 0,
      point_count: 1,
      requests: plan.requests,
    } satisfies DaemonUiApi["instrumentCollectCommand"]),
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

export function instrumentAcquisitionReadiness(
  target: InstrumentAcquisitionTarget,
  state?: InstrumentState,
): InstrumentAcquisitionReadiness {
  const plan = planInstrumentAcquisition(target, state);
  return plan.ready ? { ready: true } : { ready: false, reason: plan.reason };
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
  operation: "state" | "state/apply" | "invoke" | "collect",
): string {
  return (
    `${SESSION_API}/${encodeURIComponent(sessionId)}/instruments/` +
    `${encodeURIComponent(instrumentId)}/${operation}`
  );
}

function stateAxisSize(
  state: InstrumentState | undefined,
  target: InstrumentAcquisitionTarget,
  axisId: string,
): number | undefined {
  const candidates = [
    axisId,
    `${axisId}_points`,
    axisId === "frequency" ? "points" : undefined,
  ].filter((value): value is string => value !== undefined);
  const property = (state?.properties ?? []).find(
    (candidate) =>
      candidate.interface_id === target.interfaceId &&
      samePath(candidate.component_path ?? [], target.componentPath) &&
      candidates.includes(candidate.property_id) &&
      typeof candidate.value === "number" &&
      Number.isInteger(candidate.value) &&
      candidate.value > 0,
  );
  return typeof property?.value === "number" ? property.value : undefined;
}

type InstrumentCollectRequests = DaemonUiApi["instrumentCollectCommand"]["requests"];
type InstrumentCollectResultRequest = InstrumentCollectRequests[number];

type InstrumentAcquisitionResultSelection =
  | {
      ready: true;
      results: InstrumentAcquisitionResult[];
    }
  | {
      ready: false;
      reason: string;
    };

type InstrumentCollectPlan =
  | {
      ready: true;
      requests: InstrumentCollectRequests;
    }
  | {
      ready: false;
      reason: string;
    };

function planInstrumentAcquisition(
  target: InstrumentAcquisitionTarget,
  state?: InstrumentState,
): InstrumentCollectPlan {
  const selection = acquisitionResultsForState(target.acquisition, state);
  if (!selection.ready) return selection;
  const [firstResult, ...remainingResults] = selection.results;
  if (!firstResult) {
    return {
      ready: false,
      reason: "Collect is unavailable because the acquisition declares no results.",
    };
  }
  const requests: InstrumentCollectResultRequest[] = [];
  for (const result of [firstResult, ...remainingResults]) {
    const axes = result.axes ?? [];
    const dimensions = axes.map((axis) => {
      const size = axis.size ?? stateAxisSize(state, target, axis.id);
      return size === undefined
        ? undefined
        : {
            id: axis.id,
            kind: axis.kind,
            size,
            unit: axis.unit,
          };
    });
    const allDimensionsResolved = dimensions.every(
      (dimension): dimension is NonNullable<typeof dimension> => dimension !== undefined,
    );
    const allAxesDynamic = axes.length > 0 && axes.every((axis) => axis.size == null);
    if (!allDimensionsResolved && !allAxesDynamic) {
      const missingAxes = axes
        .filter((_, index) => dimensions[index] === undefined)
        .map((axis) => axis.label ?? axis.id);
      const resultLabel = result.label ?? result.id;
      return {
        ready: false,
        reason:
          `Collect is unavailable until ${resultLabel} has a positive point count for ` +
          `${formatList(missingAxes)}. Refresh state after configuring the sweep.`,
      };
    }
    requests.push({
      id: result.id,
      interface_id: target.interfaceId,
      component_path: target.componentPath,
      acquisition_id: target.acquisition.id,
      result_id: result.id,
      unit: result.unit,
      dtype: result.dtype,
      dimensions: allDimensionsResolved ? dimensions : [],
    });
  }
  return { ready: true, requests: [requests[0]!, ...requests.slice(1)] };
}

export function acquisitionResultsForState(
  acquisition: InstrumentAcquisition,
  state?: InstrumentState,
): InstrumentAcquisitionResultSelection {
  if (acquisition.kind === "fixed") {
    return { ready: true, results: acquisition.results };
  }
  const discriminator = (state?.properties ?? []).find(
    (property) =>
      property.interface_id === acquisition.discriminator.interface_id &&
      samePath(property.component_path ?? [], acquisition.discriminator.component_path ?? []) &&
      property.property_id === acquisition.discriminator.property_id,
  );
  if (typeof discriminator?.value !== "string") {
    return {
      ready: false,
      reason: "Collect is unavailable until the instrument mode is synchronized.",
    };
  }
  const selectedCase = acquisition.cases.find(
    (candidate) => candidate.value === discriminator.value,
  );
  if (!selectedCase) {
    return {
      ready: false,
      reason: `Collect is unavailable in instrument mode ${discriminator.value}.`,
    };
  }
  return { ready: true, results: selectedCase.results };
}

export function declaredAcquisitionResults(
  acquisition: InstrumentAcquisition,
): InstrumentAcquisitionResult[] {
  return acquisition.kind === "fixed"
    ? acquisition.results
    : acquisition.cases.flatMap((candidate) => candidate.results);
}

function samePath(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function formatList(values: string[]): string {
  if (values.length <= 1) return values[0] ?? "its dynamic axis";
  if (values.length === 2) return `${values[0]} and ${values[1]}`;
  return `${values.slice(0, -1).join(", ")}, and ${values.at(-1)}`;
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

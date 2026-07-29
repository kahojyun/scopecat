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
export type InstrumentCollectCommand = DaemonUiApi["instrumentCollectCommand"];

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

export type InstrumentAcquisitionReadiness =
  | {
      ready: true;
      status: "ready";
    }
  | {
      ready: false;
      status: "blocked" | "unknown";
      reason: string;
    };

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
  command: InstrumentCollectCommand,
): Promise<InstrumentCollectReceipt> {
  return request<InstrumentCollectReceipt>(
    instrumentSessionPath(session.session_id, command.instrument_id, "collect"),
    undefined,
    jsonRequest(command),
  );
}

export function createInstrumentCollectCommand(
  instrumentId: string,
  target: InstrumentAcquisitionTarget,
  state?: InstrumentState,
  commandId = createInstrumentCommandId("collect"),
): InstrumentCollectCommand {
  if (state && state.instrument_id !== instrumentId) {
    throw new Error(
      `Cannot collect from ${instrumentId} using state synchronized from ${state.instrument_id}.`,
    );
  }
  const plan = planInstrumentAcquisition(target, state);
  if (!plan.ready) throw new Error(plan.reason);
  return {
    command_id: commandId,
    instrument_id: instrumentId,
    point_index: 0,
    point_count: 1,
    requests: plan.requests,
  };
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
  return plan.ready
    ? { ready: true, status: "ready" }
    : { ready: false, status: plan.status, reason: plan.reason };
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

function acquisitionAxisSize(
  state: InstrumentState | undefined,
  axis: NonNullable<InstrumentAcquisitionResult["axes"]>[number],
): number | undefined {
  const source = axis.size;
  if (typeof source === "number") return source;
  const property = (state?.properties ?? []).find(
    (candidate) =>
      candidate.interface_id === source.interface_id &&
      samePath(candidate.component_path ?? [], source.component_path ?? []) &&
      candidate.property_id === source.property_id &&
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
      preconditions: InstrumentAcquisition["preconditions"];
    }
  | {
      ready: false;
      status: "blocked" | "unknown";
      reason: string;
    };

type InstrumentCollectPlan =
  | {
      ready: true;
      requests: InstrumentCollectRequests;
    }
  | {
      ready: false;
      status: "blocked" | "unknown";
      reason: string;
    };

function planInstrumentAcquisition(
  target: InstrumentAcquisitionTarget,
  state?: InstrumentState,
): InstrumentCollectPlan {
  const selection = acquisitionResultsForState(target.acquisition, state);
  if (!selection.ready) {
    const commonReadiness = acquisitionPreconditionReadiness(
      target.acquisition.preconditions ?? [],
      state,
    );
    return !commonReadiness.ready && commonReadiness.status === "blocked"
      ? commonReadiness
      : selection;
  }
  const preconditionReadiness = acquisitionPreconditionReadiness(
    [...(target.acquisition.preconditions ?? []), ...(selection.preconditions ?? [])],
    state,
  );
  if (!preconditionReadiness.ready) return preconditionReadiness;
  const [firstResult, ...remainingResults] = selection.results;
  if (!firstResult) {
    return {
      ready: false,
      status: "blocked",
      reason: "Collect is unavailable because the acquisition declares no results.",
    };
  }
  const requests: InstrumentCollectResultRequest[] = [];
  for (const result of [firstResult, ...remainingResults]) {
    const axes = result.axes ?? [];
    const dimensions = axes.map((axis) => {
      const size = acquisitionAxisSize(state, axis);
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
    if (!allDimensionsResolved) {
      const missingAxes = axes
        .filter((_, index) => dimensions[index] === undefined)
        .map((axis) => axis.label ?? axis.id);
      const resultLabel = result.label ?? result.id;
      return {
        ready: false,
        status: "unknown",
        reason:
          `Collect is unavailable until synchronized state provides a positive size for ` +
          `${formatList(missingAxes)} in ${resultLabel}. Refresh instrument state before collecting.`,
      };
    }
    requests.push({
      id: result.id,
      interface_id: target.interfaceId,
      component_path: [...target.componentPath],
      acquisition_id: target.acquisition.id,
      result_id: result.id,
      unit: result.unit,
      dtype: result.dtype,
      dimensions,
    });
  }
  return { ready: true, requests: [requests[0]!, ...requests.slice(1)] };
}

export function acquisitionResultsForState(
  acquisition: InstrumentAcquisition,
  state?: InstrumentState,
): InstrumentAcquisitionResultSelection {
  if (acquisition.kind === "fixed") {
    return {
      ready: true,
      results: acquisition.results,
      preconditions: [],
    };
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
      status: "unknown",
      reason: "Collect is unavailable until the instrument mode is synchronized.",
    };
  }
  const selectedCase = acquisition.cases.find(
    (candidate) => candidate.value === discriminator.value,
  );
  if (!selectedCase) {
    return {
      ready: false,
      status: "unknown",
      reason:
        `Collect cannot match instrument mode ${discriminator.value}. ` +
        "Refresh the instrument state.",
    };
  }
  return {
    ready: true,
    results: selectedCase.results,
    preconditions: selectedCase.preconditions,
  };
}

function acquisitionPreconditionReadiness(
  preconditions: NonNullable<InstrumentAcquisition["preconditions"]>,
  state?: InstrumentState,
): InstrumentAcquisitionReadiness {
  let unknownReason: string | undefined;
  for (const precondition of preconditions) {
    const observed = statePropertyValue(
      state,
      precondition.property.interface_id,
      precondition.property.component_path ?? [],
      precondition.property.property_id,
    );
    if (observed === undefined) {
      unknownReason ??= precondition.unavailable_reason;
      continue;
    }
    const matches = statePreconditionMatches(observed, precondition.operator, precondition.value);
    if (matches === undefined) {
      unknownReason ??= precondition.unavailable_reason;
      continue;
    }
    if (!matches) {
      return {
        ready: false,
        status: "blocked",
        reason: precondition.unavailable_reason,
      };
    }
  }
  return unknownReason ? unknownPrecondition(unknownReason) : { ready: true, status: "ready" };
}

function unknownPrecondition(reason: string): InstrumentAcquisitionReadiness {
  return {
    ready: false,
    status: "unknown",
    reason: `Refresh state to verify acquisition readiness. ${reason}`,
  };
}

function statePreconditionMatches(
  observed: InstrumentStateValue,
  operator: NonNullable<InstrumentAcquisition["preconditions"]>[number]["operator"],
  expected: InstrumentStateValue,
): boolean | undefined {
  if (operator === "equal" || operator === "not_equal") {
    const equal = equalStateValues(observed, expected);
    return equal === undefined ? undefined : operator === "equal" ? equal : !equal;
  }
  const values = orderedStateValues(observed, expected);
  if (!values) return undefined;
  const [left, right] = values;
  switch (operator) {
    case "less_than":
      return left < right;
    case "less_than_or_equal":
      return left <= right;
    case "greater_than":
      return left > right;
    case "greater_than_or_equal":
      return left >= right;
  }
}

function equalStateValues(
  observed: InstrumentStateValue,
  expected: InstrumentStateValue,
): boolean | undefined {
  if (
    typeof observed === "boolean" ||
    typeof observed === "number" ||
    typeof observed === "string"
  ) {
    return typeof observed === typeof expected ? observed === expected : undefined;
  }
  const values = orderedStateValues(observed, expected);
  return values ? values[0] === values[1] : undefined;
}

function orderedStateValues(
  observed: InstrumentStateValue,
  expected: InstrumentStateValue,
): [number, number] | undefined {
  if (typeof observed === "number" && typeof expected === "number") {
    return [observed, expected];
  }
  const left = quantityStateValue(observed);
  const right = quantityStateValue(expected);
  return left && right && left.unit === right.unit ? [left.value, right.value] : undefined;
}

function quantityStateValue(
  value: InstrumentStateValue,
): { value: number; unit: string } | undefined {
  if (
    typeof value === "object" &&
    value !== null &&
    "value" in value &&
    "unit" in value &&
    typeof value.value === "number" &&
    typeof value.unit === "string"
  ) {
    return value;
  }
  return undefined;
}

function statePropertyValue(
  state: InstrumentState | undefined,
  interfaceId: string,
  componentPath: string[],
  propertyId: string,
): InstrumentStateValue | undefined {
  return (state?.properties ?? []).find(
    (property) =>
      property.interface_id === interfaceId &&
      samePath(property.component_path ?? [], componentPath) &&
      property.property_id === propertyId,
  )?.value;
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
  if (values.length <= 1) return values[0]!;
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

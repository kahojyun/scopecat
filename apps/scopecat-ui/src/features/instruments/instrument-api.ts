import { ApiError, request } from "../../api";
import type {
  ConfigProfileSnapshot,
  DaemonUiApi,
  InstrumentApplyReceipt,
  InstrumentCapability,
  InstrumentCollectReceipt,
  InstrumentConnection,
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

export interface StagedInstrumentField {
  capabilityId: string;
  fieldPath: string;
  value: InstrumentStateValue;
}

export interface InstrumentCollectionReadiness {
  ready: boolean;
  reason?: string;
}

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
  operationId = createInstrumentOperationId("open"),
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
  fields: StagedInstrumentField[],
  operationId = createInstrumentOperationId("apply"),
): Promise<InstrumentApplyReceipt> {
  return request<InstrumentApplyReceipt>(
    instrumentSessionPath(session.session_id, instrumentId, "state/apply"),
    undefined,
    jsonRequest({
      operation_id: operationId,
      instrument_id: instrumentId,
      fields: fields.map((field) => ({
        resource_id: instrumentId,
        capability_id: field.capabilityId,
        field_path: field.fieldPath,
        value: field.value,
      })),
    } satisfies DaemonUiApi["instrumentApplyCommand"]),
  );
}

export async function collectInstrumentCapability(
  session: InstrumentSession,
  instrumentId: string,
  capability: InstrumentCapability,
  state?: InstrumentState,
  operationId = createInstrumentOperationId("collect"),
): Promise<InstrumentCollectReceipt> {
  const plan = planInstrumentCollection(capability, state);
  if (!plan.ready) throw new Error(plan.reason);
  return request<InstrumentCollectReceipt>(
    instrumentSessionPath(session.session_id, instrumentId, "collect"),
    undefined,
    jsonRequest({
      operation_id: operationId,
      instrument_id: instrumentId,
      point_index: 0,
      point_count: 1,
      requests: plan.requests,
    } satisfies DaemonUiApi["instrumentCollectCommand"]),
  );
}

export function instrumentCollectionReadiness(
  capability: InstrumentCapability,
  state?: InstrumentState,
): InstrumentCollectionReadiness {
  const plan = planInstrumentCollection(capability, state);
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
  const suffix = createInstrumentOperationId("config");
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

export function connectionSummary(connection: InstrumentView["spec"]["connection"]): string {
  switch (connection.kind) {
    case "virtual":
      return "Virtual · local simulator";
    case "tcpip_socket":
      return `TCP/IP · ${connection.host}:${connection.port}`;
  }
}

export function createInstrumentOperationId(prefix: string): string {
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
  operation: "state" | "state/apply" | "collect",
): string {
  return (
    `${SESSION_API}/${encodeURIComponent(sessionId)}/instruments/` +
    `${encodeURIComponent(instrumentId)}/${operation}`
  );
}

function stateAxisSize(state: InstrumentState | undefined, axisId: string): number | undefined {
  const candidates = [
    axisId,
    `${axisId}_points`,
    axisId === "frequency" ? "points" : undefined,
  ].filter((value): value is string => value !== undefined);
  const field = (state?.fields ?? []).find(
    (candidate) =>
      candidates.includes(candidate.field_path) &&
      typeof candidate.value === "number" &&
      Number.isInteger(candidate.value) &&
      candidate.value > 0,
  );
  return typeof field?.value === "number" ? field.value : undefined;
}

type InstrumentCollectProductRequest = NonNullable<
  DaemonUiApi["instrumentCollectCommand"]["requests"]
>[number];

type InstrumentCollectPlan =
  | {
      ready: true;
      requests: InstrumentCollectProductRequest[];
    }
  | {
      ready: false;
      reason: string;
    };

function planInstrumentCollection(
  capability: InstrumentCapability,
  state?: InstrumentState,
): InstrumentCollectPlan {
  const requests: InstrumentCollectProductRequest[] = [];
  for (const product of capability.products ?? []) {
    const axes = product.axes ?? [];
    const dimensions = axes.map((axis) => {
      const size = axis.size ?? stateAxisSize(state, axis.id);
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
      const productLabel = product.label ?? product.key;
      return {
        ready: false,
        reason:
          `Collect is unavailable until ${productLabel} has a positive point count for ` +
          `${formatList(missingAxes)}. Refresh state after configuring the sweep.`,
      };
    }
    requests.push({
      id: product.key,
      capability_id: capability.id,
      unit: product.unit,
      dtype: product.dtype,
      dimensions: allDimensionsResolved ? dimensions : [],
    });
  }
  return { ready: true, requests };
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

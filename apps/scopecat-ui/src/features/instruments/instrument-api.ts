import { ApiError } from "../../api-client";
import { apiClient, apiData } from "../../api-client";
import type {
  ActiveConfig,
  ConfigProfileSnapshot,
  DriverCatalog,
  InstrumentAcquisition,
  InstrumentApplyReceipt,
  InstrumentCollectReceipt,
  InstrumentConfiguredDefaultsApplyReceipt,
  InstrumentDriverProbeCommand,
  InstrumentDriverProbeReceipt,
  InstrumentInvokeReceipt,
  InstrumentInvokeCommand,
  InstrumentList,
  InstrumentOperation,
  InstrumentSession,
  InstrumentSessionLease,
  InstrumentSpec,
  InstrumentState,
  InstrumentStateValue,
  InstrumentView,
} from "../../api-contract";
import { setConfigDefault } from "../config/config-api";
import { safeConfigEntryId } from "../config/config-utils";

export type { ActiveConfig, InstrumentList } from "../../api-contract";

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

export type InstrumentOperationArgument = NonNullable<InstrumentInvokeCommand["arguments"]>[number];

export async function getInstruments(signal?: AbortSignal): Promise<InstrumentList> {
  return apiData(apiClient.GET("/api/v1/instruments", { signal }));
}

export async function getDriverCatalog(signal?: AbortSignal): Promise<DriverCatalog> {
  return apiData(apiClient.GET("/api/v1/instrument-drivers", { signal }));
}

export async function probeInstrumentDriver(
  command: InstrumentDriverProbeCommand,
): Promise<InstrumentDriverProbeReceipt> {
  return apiData(
    apiClient.POST("/api/v1/instrument-drivers/probe", {
      body: command,
    }),
  );
}

export async function getActiveConfig(signal?: AbortSignal): Promise<ActiveConfig> {
  return apiData(apiClient.GET("/api/v1/config-registry/active", { signal }));
}

export async function openInstrumentSession(
  instrumentId: string,
  actor: string,
  operationId = createInstrumentCommandId("open"),
): Promise<InstrumentSession> {
  return apiData(
    apiClient.POST("/api/v1/instrument-sessions", {
      body: {
        operation_id: operationId,
        actor,
        instrument_ids: [instrumentId],
        temporary_bindings: [],
      },
    }),
  );
}

export async function renewInstrumentSession(sessionId: string): Promise<InstrumentSessionLease> {
  return apiData(
    apiClient.POST("/api/v1/instrument-sessions/{session_id}/heartbeat", {
      params: { path: { session_id: sessionId } },
    }),
  );
}

export async function readInstrumentState(
  session: InstrumentSession,
  instrumentId: string,
): Promise<InstrumentState> {
  return apiData(
    apiClient.GET("/api/v1/instrument-sessions/{session_id}/instruments/{instrument_id}/state", {
      params: {
        path: {
          session_id: session.session_id,
          instrument_id: instrumentId,
        },
      },
    }),
  );
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
  return apiData(
    apiClient.POST(
      "/api/v1/instrument-sessions/{session_id}/instruments/{instrument_id}/state/apply",
      {
        params: {
          path: {
            session_id: session.session_id,
            instrument_id: instrumentId,
          },
        },
        body: {
          command_id: commandId,
          instrument_id: instrumentId,
          assignments: [assignment(first), ...remaining.map(assignment)],
        },
      },
    ),
  );
}

export async function applyInstrumentConfiguredDefaults(
  session: InstrumentSession,
  instrumentId: string,
  operationId = createInstrumentCommandId("configured-defaults"),
): Promise<InstrumentConfiguredDefaultsApplyReceipt> {
  return apiData(
    apiClient.POST(
      "/api/v1/instrument-sessions/{session_id}/instruments/{instrument_id}/configured-defaults/apply",
      {
        params: {
          path: {
            session_id: session.session_id,
            instrument_id: instrumentId,
          },
        },
        body: { operation_id: operationId },
      },
    ),
  );
}

export async function collectInstrumentAcquisition(
  session: InstrumentSession,
  instrumentId: string,
  target: InstrumentAcquisitionTarget,
  commandId = createInstrumentCommandId("collect"),
): Promise<InstrumentCollectReceipt> {
  return apiData(
    apiClient.POST("/api/v1/instrument-sessions/{session_id}/instruments/{instrument_id}/collect", {
      params: {
        path: {
          session_id: session.session_id,
          instrument_id: instrumentId,
        },
      },
      body: {
        command_id: commandId,
        instrument_id: instrumentId,
        interface_id: target.interfaceId,
        component_path: target.componentPath,
        acquisition_id: target.acquisition.id,
        result_ids: [],
      },
    }),
  );
}

export async function invokeInstrumentOperation(
  session: InstrumentSession,
  instrumentId: string,
  target: InstrumentOperationTarget,
  arguments_: InstrumentOperationArgument[],
  commandId = createInstrumentCommandId("invoke"),
): Promise<InstrumentInvokeReceipt> {
  return apiData(
    apiClient.POST("/api/v1/instrument-sessions/{session_id}/instruments/{instrument_id}/invoke", {
      params: {
        path: {
          session_id: session.session_id,
          instrument_id: instrumentId,
        },
      },
      body: {
        command_id: commandId,
        instrument_id: instrumentId,
        resource_id: instrumentId,
        interface_id: target.interfaceId,
        component_path: target.componentPath,
        operation_id: target.operation.id,
        arguments: arguments_,
      },
    }),
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
  const params = { path: { session_id: sessionId } };
  if (action === "close") {
    await apiData(
      apiClient.POST("/api/v1/instrument-sessions/{session_id}/close", {
        params,
        keepalive,
      }),
    );
    return;
  }
  await apiData(
    apiClient.POST("/api/v1/instrument-sessions/{session_id}/abort", {
      params,
      keepalive,
    }),
  );
}

export async function resolveInstrumentAttention(sessionId: string): Promise<void> {
  await apiData(
    apiClient.POST("/api/v1/instrument-sessions/{session_id}/attention", {
      params: { path: { session_id: sessionId } },
    }),
  );
}

export async function publishInstrumentSpec({
  active,
  spec,
  originalInstrumentId,
  actor,
  note,
}: {
  active: ActiveConfig;
  spec: InstrumentSpec;
  originalInstrumentId?: string;
  actor: string;
  note: string;
}): Promise<void> {
  const config = cloneConfig(active.config);
  const instruments = config.system.instrument_registry.instruments;
  if (originalInstrumentId === undefined) {
    if (instruments.some((instrument) => instrument.id === spec.id)) {
      throw new Error(`The active config already contains ${spec.id}.`);
    }
    instruments.push(spec);
  } else {
    const index = instruments.findIndex((instrument) => instrument.id === originalInstrumentId);
    if (index < 0) {
      throw new Error(`The active config no longer contains ${originalInstrumentId}.`);
    }
    instruments[index] = spec;
  }
  const suffix = createInstrumentCommandId("config");
  const entryId = safeConfigEntryId(`${config.id}-instrument-${spec.id}-${suffix}`);
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

function cloneConfig(source: ActiveConfig["config"]): ConfigProfileSnapshot {
  return JSON.parse(JSON.stringify(source)) as ConfigProfileSnapshot;
}

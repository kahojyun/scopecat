import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  ConfigProfileSnapshot,
  InstrumentAcquisition,
  InstrumentConnection,
  InstrumentOperation,
  InstrumentSession,
} from "../../api-contract";
import { setConfigDefault } from "../config/config-api";
import {
  applyInstrumentState,
  closeInstrumentSession,
  collectInstrumentAcquisition,
  connectionSummary,
  invokeInstrumentOperation,
  openInstrumentSession,
  publishInstrumentConnection,
  type ActiveConfig,
} from "./instrument-api";

vi.mock("../config/config-api", () => ({
  setConfigDefault: vi.fn(),
}));

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("instrument configuration publishing", () => {
  it("publishes a complete cloned active profile with generation fencing", async () => {
    const randomUUID = vi.fn(() => "123e4567-e89b-12d3-a456-426614174000");
    vi.stubGlobal("crypto", { randomUUID });
    const active = activeConfig();
    const connection: InstrumentConnection = {
      kind: "tcpip_socket",
      host: "192.0.2.24",
      port: 5025,
      timeout_seconds: 8,
      options: { termination: "lf" },
    };

    await publishInstrumentConnection({
      active,
      instrumentId: "vna-1",
      connection,
      actor: "Ada",
      note: "Move to the instrument VLAN",
    });

    expect(setConfigDefault).toHaveBeenCalledOnce();
    const command = vi.mocked(setConfigDefault).mock.calls[0]![0];
    expect(command).toMatchObject({
      actor: "Ada",
      note: "Move to the instrument VLAN",
      expected_generation: 7,
      source: { kind: "direct_config_profile" },
    });
    expect(command.entry_id).toBe(
      "lab-instrument-vna-1-ui-config-123e4567-e89b-12d3-a456-426614174000",
    );
    expect(randomUUID).toHaveBeenCalledOnce();
    if (command.source.kind !== "direct_config_profile") {
      throw new Error("Expected a direct config profile revision.");
    }
    expect(command.source.config.id).toBe(command.entry_id);
    expect(command.source.config.system.instrument_registry.instruments).toEqual([
      {
        id: "vna-1",
        driver_id: "keysight.pna",
        connection,
        run_preparation: { kind: "preserve" },
      },
      {
        id: "fridge",
        driver_id: "virtual.temperature",
        connection: { kind: "virtual" },
        run_preparation: { kind: "preserve" },
      },
    ]);
    expect(command.source.config.parameter_snapshot.values).toEqual([
      { id: "readout.frequency", shape: "scalar", value: { value: 6.2, unit: "GHz" } },
    ]);
    expect(active.config.system.instrument_registry.instruments[0]?.connection).toEqual({
      kind: "tcpip_socket",
      host: "192.0.2.20",
      port: 5025,
      timeout_seconds: 5,
    });
  });

  it("summarizes a TCP endpoint without rendering driver options", () => {
    expect(
      connectionSummary({
        kind: "tcpip_socket",
        host: "192.0.2.24",
        port: 5025,
        timeout_seconds: 5,
        options: { termination: "lf" },
      }),
    ).toBe("TCP/IP · 192.0.2.24:5025");
  });
});

describe("interactive collection request shaping", () => {
  it("shapes GUI operation arguments without exposing a payload map", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            status: "invoked",
            problems: [],
            state: { instrument_id: "vna-1", properties: [] },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const operation: InstrumentOperation = {
      id: "recalibrate",
      arguments: [
        {
          id: "delay",
          value_type: { type: "quantity", finite: true, unit: "s" },
        },
      ],
    };

    await invokeInstrumentOperation(
      session(),
      "vna-1",
      {
        interfaceId: "scopecat.network_sweep/v1",
        componentPath: ["source"],
        operation,
      },
      [{ id: "delay", value: { value: 0.25, unit: "s" } }],
      "invoke-retry",
    );

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "/api/v1/instrument-sessions/session-1/instruments/vna-1/invoke",
    );
    expect(requestBody(fetchMock.mock.calls[0]?.[1])).toEqual({
      command_id: "invoke-retry",
      instrument_id: "vna-1",
      resource_id: "vna-1",
      interface_id: "scopecat.network_sweep/v1",
      component_path: ["source"],
      operation_id: "recalibrate",
      arguments: [{ id: "delay", value: { value: 0.25, unit: "s" } }],
    });
  });

  it("leaves a wholly dynamic result unspecified until every axis is known", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            status: "collected",
            problems: [],
            readback: { values: {} },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const acquisition: InstrumentAcquisition = {
      id: "sweep",
      results: [
        {
          id: "trace",
          dtype: "float64",
          axes: [{ id: "frequency", kind: "frequency", unit: "Hz" }],
        },
      ],
    };
    const target = {
      interfaceId: "scopecat.network_sweep/v1",
      componentPath: [],
      acquisition,
    };

    await collectInstrumentAcquisition(session(), "vna-1", target);
    await collectInstrumentAcquisition(session(), "vna-1", target, {
      instrument_id: "vna-1",
      properties: [
        {
          interface_id: "scopecat.network_sweep/v1",
          component_path: [],
          property_id: "points",
          value: 201,
        },
      ],
    });

    const firstBody = requestBody(fetchMock.mock.calls[0]?.[1]);
    expect(firstBody.requests?.[0]!.dimensions).toEqual([]);
    expect(firstBody.requests?.[0]).toMatchObject({
      id: "trace",
      interface_id: "scopecat.network_sweep/v1",
      component_path: [],
      acquisition_id: "sweep",
      result_id: "trace",
    });
    const secondBody = requestBody(fetchMock.mock.calls[1]?.[1]);
    expect(secondBody.requests?.[0]!.dimensions).toEqual([
      { id: "frequency", kind: "frequency", size: 201, unit: "Hz" },
    ]);
  });

  it("rejects mixed static and unresolved dynamic axes before HTTP", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const acquisition: InstrumentAcquisition = {
      id: "sweep",
      results: [
        {
          id: "trace",
          label: "S-parameter trace",
          dtype: "float64",
          axes: [
            { id: "frequency", label: "Frequency", kind: "frequency", unit: "Hz" },
            { id: "receiver", kind: "receiver", size: 2 },
          ],
        },
      ],
    };
    const target = {
      interfaceId: "scopecat.network_sweep/v1",
      componentPath: [],
      acquisition,
    };

    await expect(collectInstrumentAcquisition(session(), "vna-1", target)).rejects.toThrow(
      "Collect is unavailable until S-parameter trace has a positive point count for Frequency.",
    );
    expect(fetchMock).not.toHaveBeenCalled();

    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "collected",
          problems: [],
          readback: { values: {} },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    await collectInstrumentAcquisition(session(), "vna-1", target, {
      instrument_id: "vna-1",
      properties: [
        {
          interface_id: "scopecat.network_sweep/v1",
          component_path: [],
          property_id: "points",
          value: 201,
        },
      ],
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const body = requestBody(fetchMock.mock.calls[0]?.[1]);
    expect(body.requests?.[0]!.dimensions).toEqual([
      { id: "frequency", kind: "frequency", size: 201, unit: "Hz" },
      { id: "receiver", kind: "receiver", size: 2 },
    ]);
  });

  it("uses caller idempotency ids across repeated mutating requests", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        new Response("{}", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const acquisition: InstrumentAcquisition = {
      id: "sweep",
      results: [{ id: "trace", dtype: "float64", axes: [] }],
    };
    const target = {
      interfaceId: "scopecat.network_sweep/v1",
      componentPath: [],
      acquisition,
    };
    const operationTarget = {
      interfaceId: "scopecat.network_sweep/v1",
      componentPath: [],
      operation: { id: "recalibrate", arguments: [] },
    };

    await openInstrumentSession("vna-1", "Ada", "open-retry");
    await openInstrumentSession("vna-1", "Ada", "open-retry");
    const properties = [
      {
        interfaceId: "scopecat.network_sweep/v1",
        componentPath: [],
        propertyId: "points",
        value: 201,
      },
    ];
    await applyInstrumentState(session(), "vna-1", properties, "apply-retry");
    await applyInstrumentState(session(), "vna-1", properties, "apply-retry");
    await invokeInstrumentOperation(session(), "vna-1", operationTarget, [], "invoke-retry");
    await invokeInstrumentOperation(session(), "vna-1", operationTarget, [], "invoke-retry");
    await collectInstrumentAcquisition(session(), "vna-1", target, undefined, "collect-retry");
    await collectInstrumentAcquisition(session(), "vna-1", target, undefined, "collect-retry");
    await closeInstrumentSession("session-1");
    await closeInstrumentSession("session-1");

    const bodies = fetchMock.mock.calls.slice(0, 8).map(([, init]) => requestBody(init));
    expect(bodies.slice(0, 2).map((body) => body.operation_id)).toEqual([
      "open-retry",
      "open-retry",
    ]);
    expect(bodies.slice(2, 4).map((body) => body.command_id)).toEqual([
      "apply-retry",
      "apply-retry",
    ]);
    expect(bodies.slice(4, 6).map((body) => body.command_id)).toEqual([
      "invoke-retry",
      "invoke-retry",
    ]);
    expect(bodies.slice(4, 6).map((body) => body.operation_id)).toEqual([
      "recalibrate",
      "recalibrate",
    ]);
    expect(bodies.slice(6, 8).map((body) => body.command_id)).toEqual([
      "collect-retry",
      "collect-retry",
    ]);
    expect(fetchMock.mock.calls.slice(8, 10).map(([input]) => String(input))).toEqual([
      "/api/v1/instrument-sessions/session-1/close",
      "/api/v1/instrument-sessions/session-1/close",
    ]);
  });
});

function activeConfig(): ActiveConfig {
  const config: ConfigProfileSnapshot = {
    id: "lab",
    system: {
      id: "system",
      primary_entity_id: "q0",
      topology: { entities: [] },
      instrument_registry: {
        instruments: [
          {
            id: "vna-1",
            driver_id: "keysight.pna",
            connection: {
              kind: "tcpip_socket",
              host: "192.0.2.20",
              port: 5025,
              timeout_seconds: 5,
            },
            run_preparation: { kind: "preserve" },
          },
          {
            id: "fridge",
            driver_id: "virtual.temperature",
            connection: { kind: "virtual" },
            run_preparation: { kind: "preserve" },
          },
        ],
      },
      routing: { bindings: [] },
      domain_target: null,
      parameter_catalog: { id: "parameters", definitions: [] },
    },
    parameter_snapshot: {
      id: "parameters",
      values: [
        {
          id: "readout.frequency",
          shape: "scalar",
          value: { value: 6.2, unit: "GHz" },
        },
      ],
    },
  };
  return {
    activation: {
      generation: 7,
      action: "activation",
      entry_id: "lab-default",
      entry_content_hash: "sha256:active",
      actor: "Grace",
      note: "",
      recorded_at: "2026-07-27T08:00:00Z",
    },
    entry: {
      id: "lab-default",
      content_hash: "sha256:active",
      config_ref: "entries/lab-default.json",
      source: { kind: "direct_config_profile" },
      actor: "Grace",
      note: "",
      recorded_at: "2026-07-27T08:00:00Z",
    },
    config,
  } as ActiveConfig;
}

function session(): InstrumentSession {
  return {
    session_id: "session-1",
    actor: "Ada",
    config_entry_id: "lab-default",
    config_content_hash: "sha256:active",
    instrument_ids: ["vna-1"],
    descriptions: [],
    opened_at: "2026-07-27T08:00:00Z",
  };
}

function requestBody(init: RequestInit | undefined): {
  command_id?: string;
  operation_id?: string;
  [key: string]: unknown;
  requests?: Array<{ dimensions: unknown[] }>;
} {
  if (typeof init?.body !== "string") throw new Error("Expected a JSON request body.");
  return JSON.parse(init.body) as {
    command_id?: string;
    operation_id?: string;
    [key: string]: unknown;
    requests?: Array<{ dimensions: unknown[] }>;
  };
}

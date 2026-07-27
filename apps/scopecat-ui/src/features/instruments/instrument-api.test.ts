import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  ConfigProfileSnapshot,
  InstrumentCapability,
  InstrumentConnection,
  InstrumentSessionLease,
} from "../../api-contract";
import { setConfigDefault } from "../config/config-api";
import {
  applyInstrumentState,
  closeInstrumentSession,
  collectInstrumentCapability,
  connectionSummary,
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
      credential_ref: "secret:lab-vna",
      options: { termination: "lf" },
    };

    await publishInstrumentConnection({
      active,
      instrumentId: "vna-1",
      driverId: "keysight.pna",
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
        kind: "vector_network_analyzer",
        driver_id: "keysight.pna",
        connection,
      },
      {
        id: "fridge",
        kind: "temperature_controller",
        driver_id: "virtual.temperature",
        connection: { kind: "virtual" },
      },
    ]);
    expect(command.source.config.parameter_snapshot.values).toEqual([
      { id: "readout.frequency", shape: "scalar", value: { value: 6.2, unit: "GHz" } },
    ]);
    expect(active.config.system.instrument_registry.instruments[0]?.driver_id).toBe("virtual.vna");
  });

  it("never includes credential references in a connection summary", () => {
    expect(
      connectionSummary({
        kind: "visa",
        resource: "TCPIP0::192.0.2.24::INSTR",
        backend: "@py",
        timeout_seconds: 5,
        credential_ref: "secret:do-not-render",
        options: { password: "also-do-not-render" },
      }),
    ).toBe("VISA · TCPIP0::192.0.2.24::INSTR");
  });
});

describe("interactive collection request shaping", () => {
  it("leaves a wholly dynamic product unspecified until every axis is known", async () => {
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
    const capability: InstrumentCapability = {
      id: "network_sweep",
      fields: [],
      products: [
        {
          key: "trace",
          dtype: "float64",
          axes: [{ id: "frequency", kind: "frequency", unit: "Hz" }],
        },
      ],
    };

    await collectInstrumentCapability(sessionLease(), "vna-1", capability);
    await collectInstrumentCapability(sessionLease(), "vna-1", capability, {
      instrument_id: "vna-1",
      fields: [
        {
          capability_id: "network_sweep",
          field_path: "points",
          value: 201,
        },
      ],
    });

    const firstBody = requestBody(fetchMock.mock.calls[0]?.[1]);
    expect(firstBody.command?.requests?.[0]!.dimensions).toEqual([]);
    const secondBody = requestBody(fetchMock.mock.calls[1]?.[1]);
    expect(secondBody.command?.requests?.[0]!.dimensions).toEqual([
      { id: "frequency", kind: "frequency", size: 201, unit: "Hz" },
    ]);
  });

  it("rejects a mixed static and unresolved dynamic product before HTTP", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const capability: InstrumentCapability = {
      id: "network_sweep",
      fields: [],
      products: [
        {
          key: "trace",
          label: "S-parameter trace",
          dtype: "float64",
          axes: [
            { id: "frequency", label: "Frequency", kind: "frequency", unit: "Hz" },
            { id: "receiver", kind: "receiver", size: 2 },
          ],
        },
      ],
    };

    await expect(collectInstrumentCapability(sessionLease(), "vna-1", capability)).rejects.toThrow(
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
    await collectInstrumentCapability(sessionLease(), "vna-1", capability, {
      instrument_id: "vna-1",
      fields: [
        {
          capability_id: "network_sweep",
          field_path: "points",
          value: 201,
        },
      ],
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const body = requestBody(fetchMock.mock.calls[0]?.[1]);
    expect(body.command?.requests?.[0]!.dimensions).toEqual([
      { id: "frequency", kind: "frequency", size: 201, unit: "Hz" },
      { id: "receiver", kind: "receiver", size: 2 },
    ]);
  });

  it("uses the caller operation id across repeated mutating requests", async () => {
    const fetchMock = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(
        new Response("{}", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const capability: InstrumentCapability = {
      id: "network_sweep",
      fields: [],
      products: [],
    };

    await openInstrumentSession("vna-1", "Ada", "open-retry");
    await openInstrumentSession("vna-1", "Ada", "open-retry");
    await applyInstrumentState(sessionLease(), "vna-1", [], "apply-retry");
    await applyInstrumentState(sessionLease(), "vna-1", [], "apply-retry");
    await collectInstrumentCapability(
      sessionLease(),
      "vna-1",
      capability,
      undefined,
      "collect-retry",
    );
    await collectInstrumentCapability(
      sessionLease(),
      "vna-1",
      capability,
      undefined,
      "collect-retry",
    );
    await closeInstrumentSession(sessionLease(), false, "close-retry");
    await closeInstrumentSession(sessionLease(), false, "close-retry");

    const bodies = fetchMock.mock.calls.map(([, init]) => requestBody(init));
    expect(bodies.slice(0, 2).map((body) => body.operation_id)).toEqual([
      "open-retry",
      "open-retry",
    ]);
    expect(bodies.slice(2, 4).map((body) => body.command?.operation_id)).toEqual([
      "apply-retry",
      "apply-retry",
    ]);
    expect(bodies.slice(4, 6).map((body) => body.command?.operation_id)).toEqual([
      "collect-retry",
      "collect-retry",
    ]);
    expect(bodies.slice(6, 8).map((body) => body.operation_id)).toEqual([
      "close-retry",
      "close-retry",
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
            kind: "vector_network_analyzer",
            driver_id: "virtual.vna",
            connection: {
              kind: "virtual",
              credential_ref: "secret:lab-vna",
              options: { termination: "lf" },
            },
          },
          {
            id: "fridge",
            kind: "temperature_controller",
            driver_id: "virtual.temperature",
            connection: { kind: "virtual" },
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

function sessionLease(): InstrumentSessionLease {
  return {
    session_id: "session-1",
    lease_id: "lease-1",
    actor: "Ada",
    config_entry_id: "lab-default",
    config_content_hash: "sha256:active",
    instrument_ids: ["vna-1"],
    descriptions: [],
    issued_at: "2026-07-27T08:00:00Z",
    expires_at: "2026-07-27T08:05:00Z",
    heartbeat_interval_seconds: 10,
  };
}

function requestBody(init: RequestInit | undefined): {
  operation_id?: string;
  command?: {
    operation_id?: string;
    requests?: Array<{ dimensions: unknown[] }>;
  };
} {
  if (typeof init?.body !== "string") throw new Error("Expected a JSON request body.");
  return JSON.parse(init.body) as {
    operation_id?: string;
    command?: {
      operation_id?: string;
      requests?: Array<{ dimensions: unknown[] }>;
    };
  };
}

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  activateConfigEntry,
  getConfigRegistry,
  getConfigRegistryEntry,
  importConfigProfile,
  parseConfigProfileJson,
  previewConfigDraft,
  registerConfigDraft,
  rollbackConfig,
  setConfigDraftDefault,
} from "./config-api";
import type { ConfigDraftCommand, JsonObject } from "./config-types";

const HASH_A = `sha256:${"a".repeat(64)}`;
const HASH_B = `sha256:${"b".repeat(64)}`;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("config registry reads", () => {
  it("polls registry metadata without loading the full active snapshot", async () => {
    const fetchMock = vi.fn((_input: string | URL | Request) =>
      Promise.resolve(
        jsonResponse({
          entries: [registryEntry("config-a", HASH_A), registryEntry("config-b", HASH_B)],
          active_state: activeState(),
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const overview = await getConfigRegistry();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/config-registry");
    expect(overview.active).toMatchObject({
      entryId: "config-b",
      contentHash: HASH_B,
      generation: 2,
    });
    expect(overview.entries.map((entry) => entry.id)).toEqual(["config-b", "config-a"]);
    expect(overview.history.map((item) => item.generation)).toEqual([2, 1]);
  });

  it("treats a missing active projection as an empty active state", async () => {
    const fetchMock = vi.fn((input: string | URL | Request) =>
      Promise.resolve(
        String(input).endsWith("/active")
          ? jsonResponse({ detail: "not found" }, 404)
          : jsonResponse({
              entries: [],
              active_state: null,
            }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getConfigRegistry()).resolves.toEqual({
      active: undefined,
      entries: [],
      history: [],
    });
  });

  it("loads one entry snapshot without expanding the registry overview", async () => {
    const fetchMock = vi.fn((_input: string | URL | Request) =>
      Promise.resolve(
        jsonResponse({
          entry: registryEntry("config-a", HASH_A),
          config: configProfile("profile-a"),
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const detail = await getConfigRegistryEntry("config a");

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/config-registry/entries/config%20a");
    expect(detail.entry.id).toBe("config-a");
    expect(detail.summary).toEqual({
      id: "profile-a",
      primaryEntityId: "q0",
      parameterCount: 3,
      instrumentCount: 1,
      connectionCount: 1,
    });
    expect(detail.config.system.parameterCatalog.definitions).toMatchObject([
      {
        id: "drive.frequency",
        valueType: {
          shape: "scalar",
          atom: { type: "quantity", unit: "GHz" },
        },
      },
      {
        id: "qubits",
        valueType: {
          shape: "table",
          primaryKey: ["qubit"],
        },
      },
      {
        id: "sweep.offsets",
        valueType: {
          shape: "series",
          itemType: { type: "float" },
          minLength: 1,
          maxLength: 4,
        },
      },
    ]);
    expect(detail.config.parameterSnapshot.values[1]).toMatchObject({
      id: "qubits",
      shape: "table",
      rows: [
        {
          qubit: { id: "q0", kind: "logical_qubit" },
          readout_frequency: { value: 6.5, unit: "GHz" },
        },
      ],
    });
  });

  it("preserves typed parameter-edit provenance from registry entries", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        jsonResponse({
          entries: [
            {
              ...registryEntry("manual-edit", HASH_A),
              source: {
                kind: "manual_parameter_updates",
                base_entry_id: "config-a",
                base_config_content_hash: HASH_B,
                base_registry_generation: 3,
              },
            },
          ],
          active_state: null,
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const overview = await getConfigRegistry();

    expect(overview.entries[0]?.source).toEqual({
      kind: "manual_parameter_updates",
      proposalIds: [],
      baseEntryId: "config-a",
      baseContentHash: HASH_B,
      baseGeneration: 3,
    });
  });
});

describe("config registry commands", () => {
  it("sends generation-checked activate and rollback commands", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(jsonResponse({})));
    vi.stubGlobal("fetch", fetchMock);
    const command = {
      operator: "Ada",
      note: "promote calibrated values",
      expectedGeneration: 2,
    };

    await activateConfigEntry("config/b", command);
    await rollbackConfig(command);

    expectRequest(fetchMock, 0, "/api/v1/config-registry/active", {
      entry_id: "config/b",
      operator: "Ada",
      note: "promote calibrated values",
      expected_generation: 2,
    });
    expectRequest(fetchMock, 1, "/api/v1/config-registry/rollback", {
      operator: "Ada",
      note: "promote calibrated values",
      expected_generation: 2,
    });
  });

  it("registers an imported snapshot without implicitly activating it", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(jsonResponse({})));
    vi.stubGlobal("fetch", fetchMock);
    const config = configProfile("profile-import");

    await importConfigProfile({
      entryId: "profile-import",
      registeredBy: "Grace",
      note: "bench setup",
      config,
    });

    expectRequest(fetchMock, 0, "/api/v1/config-registry/entries", {
      entry_id: "profile-import",
      registered_by: "Grace",
      note: "bench setup",
      config,
    });
  });
});

describe("typed config drafts", () => {
  const draft: ConfigDraftCommand = {
    baseEntryId: "config-a",
    baseContentHash: HASH_A,
    baseGeneration: 3,
    candidateId: "config-a-edit",
    updates: [
      {
        kind: "replace_parameter",
        value: {
          id: "drive.frequency",
          shape: "scalar",
          value: { value: 5.2, unit: "GHz" },
          sourceLocation: {
            uri: "calibration.xlsx",
            sheet: "drive",
            row: 2,
            column: "B",
            path: [],
          },
          metadata: { retained: true },
        },
      },
      {
        kind: "replace_parameter",
        value: {
          id: "sweep.offsets",
          shape: "series",
          items: [-0.2, 0, 0.2],
          itemLocations: [
            { uri: "old.csv", row: 1, path: [] },
            { uri: "old.csv", row: 2, path: [] },
            { uri: "old.csv", row: 3, path: [] },
          ],
          metadata: {},
        },
      },
      {
        kind: "replace_parameter",
        value: {
          id: "unkeyed",
          shape: "table",
          rows: [{ name: "q0", enabled: true }],
          rowLocations: [{ uri: "old.csv", row: 4, path: [] }],
          metadata: {},
        },
      },
      {
        kind: "update_parameter_rows",
        parameterId: "qubits",
        key: {
          qubit: {
            id: "q0",
            kind: "logical_qubit",
            metadata: { display: "Q0" },
          },
        },
        values: {
          readout_frequency: { value: 6.6, unit: "GHz" },
        },
      },
      {
        kind: "insert_parameter_rows",
        parameterId: "qubits",
        rows: [
          {
            qubit: {
              id: "q1",
              kind: "logical_qubit",
              metadata: {},
            },
            readout_frequency: { value: 6.7, unit: "GHz" },
          },
        ],
      },
      {
        kind: "delete_parameter_rows",
        parameterId: "qubits",
        key: {
          qubit: {
            id: "q2",
            kind: "logical_qubit",
            metadata: {},
          },
        },
      },
    ],
  };

  it("serializes typed operations without inherited source locations", async () => {
    const candidate = configProfile("config-a-edit");
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        jsonResponse({
          valid: true,
          base_entry: registryEntry("config-a", HASH_A),
          base_generation: 3,
          base_content_hash: HASH_A,
          config: candidate,
          result_content_hash: HASH_B,
          deltas: [
            {
              parameter_id: "drive.frequency",
              before: scalarValue(5),
              after: scalarValue(5.2),
            },
          ],
          problems: [
            {
              code: "config.note",
              impact: "advisory",
              category: "operation",
              phase: "configuration",
              message: "Review the calibrated frequency.",
              location: {
                kind: "model",
                root: "parameter_snapshot",
                path: ["values", "drive.frequency"],
              },
              related_locations: [],
              details: { source: "preview" },
              occurrence_id: null,
            },
          ],
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const preview = await previewConfigDraft(draft);

    expect(preview).toMatchObject({
      valid: true,
      baseGeneration: 3,
      baseContentHash: HASH_A,
      resultContentHash: HASH_B,
      config: { id: "config-a-edit" },
      deltas: [{ parameterId: "drive.frequency" }],
      problems: [
        {
          code: "config.note",
          impact: "advisory",
          location: {
            root: "parameter_snapshot",
            path: ["values", "drive.frequency"],
          },
        },
      ],
    });
    expectRequest(fetchMock, 0, "/api/v1/config-registry/drafts/preview", {
      base_entry_id: "config-a",
      base_content_hash: HASH_A,
      base_generation: 3,
      candidate_id: "config-a-edit",
      updates: [
        {
          kind: "replace_parameter",
          value: {
            id: "drive.frequency",
            shape: "scalar",
            value: { value: 5.2, unit: "GHz" },
            metadata: { retained: true },
          },
        },
        {
          kind: "replace_parameter",
          value: {
            id: "sweep.offsets",
            shape: "series",
            items: [-0.2, 0, 0.2],
            metadata: {},
          },
        },
        {
          kind: "replace_parameter",
          value: {
            id: "unkeyed",
            shape: "table",
            rows: [{ name: "q0", enabled: true }],
            metadata: {},
          },
        },
        {
          kind: "update_parameter_rows",
          parameter_id: "qubits",
          key: {
            qubit: {
              id: "q0",
              kind: "logical_qubit",
              metadata: { display: "Q0" },
            },
          },
          values: {
            readout_frequency: { value: 6.6, unit: "GHz" },
          },
        },
        {
          kind: "insert_parameter_rows",
          parameter_id: "qubits",
          rows: [
            {
              qubit: {
                id: "q1",
                kind: "logical_qubit",
                metadata: {},
              },
              readout_frequency: { value: 6.7, unit: "GHz" },
            },
          ],
        },
        {
          kind: "delete_parameter_rows",
          parameter_id: "qubits",
          key: {
            qubit: {
              id: "q2",
              kind: "logical_qubit",
              metadata: {},
            },
          },
        },
      ],
    });
  });

  it("keeps invalid previews problem-only and registers only an explicit draft", async () => {
    const invalidResponse = {
      valid: false,
      base_entry: registryEntry("config-a", HASH_A),
      base_generation: 3,
      base_content_hash: HASH_A,
      config: null,
      result_content_hash: null,
      deltas: [],
      problems: [
        {
          code: "config.invalid",
          impact: "blocking",
          category: "invalid_input",
          phase: "configuration",
          message: "The value is outside its accepted range.",
          location: null,
          related_locations: [],
          details: {},
          occurrence_id: null,
        },
      ],
    };
    const receipt = {
      entry: {
        ...registryEntry("config-a-edit", HASH_B),
        source: {
          kind: "manual_parameter_updates",
          base_entry_id: "config-a",
          base_config_content_hash: HASH_A,
          base_registry_generation: 3,
        },
      },
      result_content_hash: HASH_B,
      deltas: [
        {
          parameter_id: "drive.frequency",
          before: scalarValue(5),
          after: scalarValue(5.2),
        },
      ],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(invalidResponse))
      .mockResolvedValueOnce(jsonResponse(receipt, 201));
    vi.stubGlobal("fetch", fetchMock);

    await expect(previewConfigDraft(draft)).resolves.toMatchObject({
      valid: false,
      config: undefined,
      resultContentHash: undefined,
      problems: [{ code: "config.invalid", impact: "blocking" }],
    });
    const registered = await registerConfigDraft({
      draft,
      expectedResultContentHash: HASH_B,
      entryId: "config-a-edit",
      registeredBy: "Ada",
      note: "calibrated",
    });

    expect(registered).toMatchObject({
      entry: {
        id: "config-a-edit",
        source: {
          kind: "manual_parameter_updates",
          baseEntryId: "config-a",
        },
      },
      resultContentHash: HASH_B,
      deltas: [{ parameterId: "drive.frequency" }],
    });
    expectRequest(fetchMock, 1, "/api/v1/config-registry/drafts/register", {
      draft: JSON.parse(String((fetchMock.mock.calls[0]?.[1] as RequestInit | undefined)?.body)),
      expected_result_content_hash: HASH_B,
      entry_id: "config-a-edit",
      registered_by: "Ada",
      note: "calibrated",
    });
  });

  it("atomically saves a reviewed draft and sets it as the default", async () => {
    const entryId = "config-a-edit-bbbbbbbbbbbb";
    const activation = {
      id: "activation-4",
      generation: 4,
      action: "activation",
      entry_id: entryId,
      entry_content_hash: HASH_B,
      previous_entry_id: "config-a",
      operator: "Ada",
      note: "calibrated",
      recorded_at: "2026-07-24T08:10:00Z",
    };
    const entry = {
      ...registryEntry(entryId, HASH_B),
      source: {
        kind: "manual_parameter_updates",
        base_entry_id: "config-a",
        base_config_content_hash: HASH_A,
        base_registry_generation: 3,
      },
    };
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        jsonResponse({
          entry,
          result_content_hash: HASH_B,
          deltas: [
            {
              parameter_id: "drive.frequency",
              before: scalarValue(5),
              after: scalarValue(5.2),
            },
          ],
          active_state: {
            generation: 4,
            active_entry_id: entryId,
            active_entry_content_hash: HASH_B,
            updated_at: "2026-07-24T08:10:00Z",
            history: [activation],
          },
          activation,
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const receipt = await setConfigDraftDefault({
      registration: {
        draft,
        expectedResultContentHash: HASH_B,
        entryId,
        registeredBy: "Ada",
        note: "calibrated",
      },
      operator: "Ada",
      activationNote: "accepted edit",
    });

    expect(receipt).toMatchObject({
      entry: { id: entryId },
      resultContentHash: HASH_B,
      activeState: {
        generation: 4,
        entryId,
        contentHash: HASH_B,
      },
      activation: {
        generation: 4,
        entryId,
        operator: "Ada",
      },
    });
    expectRequest(fetchMock, 0, "/api/v1/config-registry/drafts/set-default", {
      registration: {
        draft: expect.objectContaining({
          base_entry_id: "config-a",
          base_content_hash: HASH_A,
          base_generation: 3,
          candidate_id: "config-a-edit",
          updates: expect.any(Array),
        }),
        expected_result_content_hash: HASH_B,
        entry_id: entryId,
        registered_by: "Ada",
        note: "calibrated",
      },
      operator: "Ada",
      activation_note: "accepted edit",
    });
  });
});

describe("config snapshot import boundary", () => {
  it("accepts only self-contained config snapshots at the upload boundary", () => {
    const config = configProfile("profile-a");

    expect(
      parseConfigProfileJson(
        JSON.stringify({
          format_version: "scopecat.config_snapshot.v1",
          ...config,
        }),
      ),
    ).toEqual(config);
    expect(() => parseConfigProfileJson("{")).toThrow("not valid JSON");
    expect(() =>
      parseConfigProfileJson(
        JSON.stringify({
          ...config,
          format_version: "scopecat.config_snapshot.v0",
        }),
      ),
    ).toThrow("Unsupported config snapshot format");
    expect(() =>
      parseConfigProfileJson(
        JSON.stringify({
          ...config,
          format_version: undefined,
        }),
      ),
    ).toThrow("missing format_version");
    expect(() =>
      parseConfigProfileJson(
        JSON.stringify({
          format_version: "scopecat.config_profile_manifest.v1",
          id: "split-profile",
        }),
      ),
    ).toThrow("must be loaded by Python");
  });
});

function registryEntry(id: string, contentHash: string) {
  return {
    id,
    config_ref: `entries/${id}.json`,
    content_hash: contentHash,
    status: "registered",
    source: { kind: "direct_config_profile" },
    registered_by: "scopecat",
    note: "",
    registered_at: id === "config-b" ? "2026-07-23T10:00:00Z" : "2026-07-22T10:00:00Z",
  };
}

function activeState() {
  return {
    generation: 2,
    active_entry_id: "config-b",
    active_entry_content_hash: HASH_B,
    updated_at: "2026-07-23T10:01:00Z",
    history: [
      {
        id: "activation-1",
        generation: 1,
        action: "activation",
        entry_id: "config-a",
        entry_content_hash: HASH_A,
        operator: "scopecat",
        recorded_at: "2026-07-22T10:01:00Z",
      },
      {
        id: "activation-2",
        generation: 2,
        action: "activation",
        entry_id: "config-b",
        entry_content_hash: HASH_B,
        previous_entry_id: "config-a",
        previous_entry_content_hash: HASH_A,
        operator: "Ada",
        recorded_at: "2026-07-23T10:01:00Z",
      },
    ],
  };
}

function scalarValue(value: number) {
  return {
    id: "drive.frequency",
    shape: "scalar",
    value: { value, unit: "GHz" },
    source_location: null,
    metadata: {},
  };
}

function configProfile(id: string): JsonObject {
  return {
    id,
    system: {
      id: "system",
      primary_entity_id: "q0",
      topology: {
        entities: [
          {
            id: "q0",
            kind: "logical_qubit",
            metadata: {},
          },
        ],
        devices: [],
        links: [],
        lines: [],
        channels: [],
        groups: [],
      },
      instrument_registry: {
        instruments: [{ id: "signal", kind: "signal_generator" }],
      },
      routing: { bindings: [] },
      domain_target: null,
      parameter_catalog: {
        id: "parameters",
        definitions: [
          {
            id: "drive.frequency",
            value_type: {
              shape: "scalar",
              atom: { type: "quantity", unit: "GHz" },
            },
            description: "Drive frequency",
            metadata: {},
          },
          {
            id: "qubits",
            value_type: {
              shape: "table",
              columns: [
                {
                  id: "qubit",
                  value_type: {
                    type: "entity",
                    entity_kind: "logical_qubit",
                  },
                },
                {
                  id: "readout_frequency",
                  value_type: { type: "quantity", unit: "GHz" },
                },
              ],
              primary_key: ["qubit"],
            },
            description: "Qubit calibration",
            metadata: {},
          },
          {
            id: "sweep.offsets",
            value_type: {
              shape: "series",
              item_type: { type: "float" },
              min_length: 1,
              max_length: 4,
            },
            description: "Sweep offsets",
            metadata: {},
          },
        ],
        metadata: {},
      },
    },
    environment: {
      id: "bench",
      connection_profile: {
        connections: [
          {
            id: "signal-usb",
            instrument_id: "signal",
            kind: "usb",
            resource_hint: null,
          },
        ],
      },
    },
    parameter_snapshot: {
      id: "parameters",
      values: [
        {
          id: "drive.frequency",
          shape: "scalar",
          value: { value: 5.0, unit: "GHz" },
          source_location: null,
          metadata: {},
        },
        {
          id: "qubits",
          shape: "table",
          rows: [
            {
              qubit: {
                id: "q0",
                kind: "logical_qubit",
                metadata: {},
              },
              readout_frequency: { value: 6.5, unit: "GHz" },
            },
          ],
          row_locations: [],
          source_location: null,
          metadata: {},
        },
        {
          id: "sweep.offsets",
          shape: "series",
          items: [-0.1, 0, 0.1],
          item_locations: [],
          source_location: null,
          metadata: {},
        },
      ],
      metadata: {},
    },
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function expectRequest(
  fetchMock: ReturnType<typeof vi.fn>,
  index: number,
  path: string,
  body: Record<string, unknown>,
) {
  const call = fetchMock.mock.calls[index];
  expect(call?.[0]).toBe(path);
  expect(call?.[1]?.method).toBe("POST");
  const headers = new Headers(call?.[1]?.headers);
  expect(headers.get("Accept")).toBe("application/json");
  expect(headers.get("Content-Type")).toBe("application/json");
  expect(JSON.parse(String(call?.[1]?.body))).toEqual(body);
}

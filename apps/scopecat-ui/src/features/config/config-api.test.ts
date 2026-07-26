import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  ConfigDraftCommand,
  ConfigProfileSnapshot,
  ConfigRegistryEntry,
} from "../../api-contract";
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

const HASH_A = `sha256:${"a".repeat(64)}`;
const HASH_B = `sha256:${"b".repeat(64)}`;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("config registry reads", () => {
  it("keeps the generated wire model and only sorts registry projections", async () => {
    const fetchMock = vi.fn((_input: string | URL | Request) =>
      Promise.resolve(
        jsonResponse({
          entries: [registryEntry("config-a", HASH_A), registryEntry("config-b", HASH_B)],
          active_state: {
            generation: 2,
            active_entry_id: "config-b",
            active_entry_content_hash: HASH_B,
            history: [activation(1, "config-a", HASH_A), activation(2, "config-b", HASH_B)],
          },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const overview = await getConfigRegistry();

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/config-registry");
    expect(overview.entries.map((entry) => entry.id)).toEqual(["config-b", "config-a"]);
    expect(overview.active_state).toMatchObject({
      active_entry_id: "config-b",
      active_entry_content_hash: HASH_B,
      generation: 2,
    });
    expect(overview.active_state?.history?.map((item) => item.generation)).toEqual([2, 1]);
  });

  it("returns null active state without inventing a second projection", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(jsonResponse({ entries: [], active_state: null }))),
    );

    await expect(getConfigRegistry()).resolves.toEqual({
      entries: [],
      active_state: null,
    });
  });

  it("uses the entry snapshot itself for summary and raw display", async () => {
    const config = configProfile("profile-a");
    const fetchMock = vi.fn((_input: string | URL | Request) =>
      Promise.resolve(
        jsonResponse({
          entry: registryEntry("config-a", HASH_A),
          config,
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const detail = await getConfigRegistryEntry("config a");

    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/config-registry/entries/config%20a");
    expect(detail.config).toEqual(config);
    expect(detail.config).not.toHaveProperty("raw");
    expect(detail.summary).toEqual({
      id: "profile-a",
      primaryEntityId: "q0",
      parameterCount: 1,
      instrumentCount: 1,
    });
  });
});

describe("config registry commands", () => {
  it("sends generated wire commands unchanged", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(jsonResponse({})));
    vi.stubGlobal("fetch", fetchMock);
    const activationCommand = {
      entry_id: "config/b",
      operator: "Ada",
      note: "promote calibrated values",
      expected_generation: 2,
    };
    const rollback = {
      operator: activationCommand.operator,
      note: activationCommand.note,
      expected_generation: activationCommand.expected_generation,
    };
    const config = configProfile("profile-import");
    const imported = {
      entry_id: "profile-import",
      registered_by: "Grace",
      note: "bench setup",
      config,
    };

    await activateConfigEntry(activationCommand);
    await rollbackConfig(rollback);
    await importConfigProfile(imported);

    expectRequest(fetchMock, 0, "/api/v1/config-registry/active", activationCommand);
    expectRequest(fetchMock, 1, "/api/v1/config-registry/rollback", rollback);
    expectRequest(fetchMock, 2, "/api/v1/config-registry/entries", imported);
  });
});

describe("typed config drafts", () => {
  const draft: ConfigDraftCommand = {
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
        },
      },
    ],
  };

  it("passes preview responses and commands through the generated contract", async () => {
    const response = {
      valid: true,
      base_entry: registryEntry("config-a", HASH_A),
      base_generation: 3,
      base_content_hash: HASH_A,
      config: configProfile("config-a-edit"),
      result_content_hash: HASH_B,
      deltas: [
        {
          parameter_id: "drive.frequency",
          before: scalarValue(5),
          after: scalarValue(5.2),
        },
      ],
      problems: [],
    };
    const fetchMock = vi.fn(() => Promise.resolve(jsonResponse(response)));
    vi.stubGlobal("fetch", fetchMock);

    await expect(previewConfigDraft(draft)).resolves.toEqual(response);
    expectRequest(fetchMock, 0, "/api/v1/config-registry/drafts/preview", draft);
  });

  it("sends register and set-default commands unchanged", async () => {
    const registration = {
      draft,
      expected_result_content_hash: HASH_B,
      entry_id: "config-a-edit",
      registered_by: "Ada",
      note: "calibrated",
    };
    const registrationReceipt = {
      entry: registryEntry("config-a-edit", HASH_B),
      result_content_hash: HASH_B,
      deltas: [
        {
          parameter_id: "drive.frequency",
          before: scalarValue(5),
          after: scalarValue(5.2),
        },
      ],
    };
    const activationRecord = activation(4, "config-a-edit", HASH_B);
    const defaultCommand = {
      registration,
      operator: "Ada",
      activation_note: "accepted edit",
    };
    const defaultReceipt = {
      ...registrationReceipt,
      active_state: {
        generation: 4,
        active_entry_id: "config-a-edit",
        active_entry_content_hash: HASH_B,
        history: [activationRecord],
      },
      activation: activationRecord,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(registrationReceipt, 201))
      .mockResolvedValueOnce(jsonResponse(defaultReceipt));
    vi.stubGlobal("fetch", fetchMock);

    await expect(registerConfigDraft(registration)).resolves.toEqual(registrationReceipt);
    await expect(setConfigDraftDefault(defaultCommand)).resolves.toEqual(defaultReceipt);
    expectRequest(fetchMock, 0, "/api/v1/config-registry/drafts/register", registration);
    expectRequest(fetchMock, 1, "/api/v1/config-registry/drafts/set-default", defaultCommand);
  });
});

describe("config snapshot import boundary", () => {
  it("accepts only self-contained config snapshots", () => {
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
          format_version: "scopecat.config_profile_manifest.v1",
          id: "split-profile",
        }),
      ),
    ).toThrow("must be loaded by Python");
  });
});

function registryEntry(id: string, contentHash: string): ConfigRegistryEntry {
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

function activation(generation: number, entryId: string, entryContentHash: string) {
  return {
    id: `activation-${generation}`,
    generation,
    action: "activation" as const,
    entry_id: entryId,
    entry_content_hash: entryContentHash,
    operator: "Ada",
    note: "",
    recorded_at: "2026-07-24T08:00:00Z",
  };
}

function scalarValue(value: number) {
  return {
    id: "drive.frequency",
    shape: "scalar" as const,
    value: { value, unit: "GHz" },
  };
}

function configProfile(id: string): ConfigProfileSnapshot {
  return {
    id,
    system: {
      id: "system",
      primary_entity_id: "q0",
      topology: {
        entities: [{ id: "q0", kind: "logical_qubit", metadata: {} }],
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
          },
        ],
      },
    },
    parameter_snapshot: {
      id: "parameters",
      values: [scalarValue(5)],
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
  body: object,
) {
  const call = fetchMock.mock.calls[index];
  expect(call?.[0]).toBe(path);
  expect(call?.[1]?.method).toBe("POST");
  expect(JSON.parse(String(call?.[1]?.body))).toEqual(body);
}

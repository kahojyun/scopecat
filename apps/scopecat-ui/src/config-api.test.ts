import { afterEach, describe, expect, it, vi } from "vitest";
import {
  activateConfigEntry,
  getConfigRegistry,
  getConfigRegistryEntry,
  importConfigProfile,
  parseConfigProfileJson,
  rollbackConfig,
} from "./config-api";

const HASH_A = `sha256:${"a".repeat(64)}`;
const HASH_B = `sha256:${"b".repeat(64)}`;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("config registry reads", () => {
  it("combines registry metadata with the active config projection", async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = String(input);
      if (path.endsWith("/active")) {
        return Promise.resolve(
          jsonResponse({
            entry: registryEntry("config-b", HASH_B),
            active_state: activeState(),
            config: configProfile("profile-b"),
          }),
        );
      }
      return Promise.resolve(
        jsonResponse({
          entries: [
            registryEntry("config-a", HASH_A),
            registryEntry("config-b", HASH_B),
          ],
          active_state: activeState(),
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const overview = await getConfigRegistry();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.map(([path]) => String(path)).sort()).toEqual([
      "/api/v1/config-registry",
      "/api/v1/config-registry/active",
    ]);
    expect(overview.active).toMatchObject({
      entryId: "config-b",
      contentHash: HASH_B,
      generation: 2,
      snapshot: {
        id: "profile-b",
        parameterCount: 2,
        instrumentCount: 1,
        connectionCount: 1,
      },
    });
    expect(overview.entries.map((entry) => entry.id)).toEqual([
      "config-b",
      "config-a",
    ]);
    expect(overview.history.map((item) => item.generation)).toEqual([2, 1]);
  });

  it("treats a missing active projection as an empty active state", async () => {
    const fetchMock = vi.fn((input: string | URL | Request) =>
      Promise.resolve(
        String(input).endsWith("/active")
          ? jsonResponse({ detail: "not found" }, 404)
          : jsonResponse({ entries: [], active_state: null }),
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

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/config-registry/entries/config%20a",
    );
    expect(detail.entry.id).toBe("config-a");
    expect(detail.snapshot).toMatchObject({
      id: "profile-a",
      labId: "lab",
      primaryEntityId: "q0",
      parameterCount: 2,
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

describe("config snapshot import boundary", () => {
  it("accepts only self-contained config snapshots at the upload boundary", () => {
    const config = configProfile("profile-a");

    expect(parseConfigProfileJson(JSON.stringify(config))).toEqual(config);
    expect(() => parseConfigProfileJson("{")).toThrow("not valid JSON");
    expect(() =>
      parseConfigProfileJson(
        JSON.stringify({
          ...config,
          schema_version: "scopecat.config_profile_snapshot.v1",
        }),
      ),
    ).toThrow("Unsupported config snapshot schema");
    expect(() =>
      parseConfigProfileJson(
        JSON.stringify({
          ...config,
          schema_version: undefined,
        }),
      ),
    ).toThrow("missing schema_version");
    expect(() =>
      parseConfigProfileJson(
        JSON.stringify({
          schema_version: "scopecat.config_profile.v2",
          id: "split-profile",
        }),
      ),
    ).toThrow("must be loaded by Python");
  });
});

function registryEntry(id: string, contentHash: string) {
  return {
    schema_version: "scopecat.config.registry_entry.v6",
    id,
    config_ref: `entries/${id}.json`,
    content_hash: contentHash,
    status: "registered",
    source: { kind: "direct_config_profile" },
    registered_by: "scopecat",
    note: "",
    registered_at:
      id === "config-b" ? "2026-07-23T10:00:00Z" : "2026-07-22T10:00:00Z",
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

function configProfile(id: string): Record<string, unknown> {
  return {
    schema_version: "scopecat.config_profile_snapshot.v2",
    id,
    system: {
      id: "system",
      workspace_id: "lab",
      primary_entity_id: "q0",
      instrument_registry: {
        instruments: [{ id: "signal", kind: "signal_generator" }],
      },
    },
    environment: {
      id: "bench",
      workspace_id: "lab",
      connection_profile: {
        connections: [{ id: "signal-usb", kind: "usb" }],
      },
    },
    parameter_snapshot: {
      id: "parameters",
      values: [
        { id: "drive.frequency", shape: "scalar", value: 5.0 },
        { id: "drive.power", shape: "scalar", value: -12 },
      ],
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
  expect(call?.[1]).toMatchObject({
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
  });
  expect(JSON.parse(String(call?.[1]?.body))).toEqual(body);
}

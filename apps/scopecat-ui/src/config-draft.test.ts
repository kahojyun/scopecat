import { describe, expect, it } from "vitest";
import { deriveConfigDraftUpdates } from "./config-draft";
import type {
  ConfigProfileSnapshot,
  ParameterEntity,
  StoredParameterValue,
} from "./config-types";

describe("deriveConfigDraftUpdates", () => {
  it("uses semantic keyed row operations and ignores entity metadata in keys", () => {
    const config = testConfig();
    const edited: StoredParameterValue = {
      id: "calibration",
      shape: "table",
      rows: [
        {
          entity: entity("q0", { display: "new label" }),
          frequency: 6.6,
        },
        {
          entity: entity("q2"),
          frequency: 6.8,
        },
      ],
      rowLocations: [],
      metadata: {},
    };

    expect(
      deriveConfigDraftUpdates(config, { calibration: edited }),
    ).toEqual([
      {
        kind: "delete_parameter_rows",
        parameterId: "calibration",
        key: { entity: entity("q1") },
      },
      {
        kind: "update_parameter_rows",
        parameterId: "calibration",
        key: { entity: entity("q0", { display: "new label" }) },
        values: { frequency: 6.6 },
      },
      {
        kind: "insert_parameter_rows",
        parameterId: "calibration",
        rows: [
          {
            entity: entity("q2"),
            frequency: 6.8,
          },
        ],
      },
    ]);
  });

  it("emits complete replacement for an unkeyed table", () => {
    const config = testConfig();
    const edited: StoredParameterValue = {
      id: "flags",
      shape: "table",
      rows: [{ name: "drive", enabled: false }],
      rowLocations: [],
      metadata: { owner: "lab" },
    };

    expect(deriveConfigDraftUpdates(config, { flags: edited })).toEqual([
      { kind: "replace_parameter", value: edited },
    ]);
  });

  it("keeps duplicate edited keys in a replacement for daemon validation", () => {
    const config = testConfig();
    const base = config.parameterSnapshot.values.find(
      (value) => value.id === "calibration",
    );
    if (base?.shape !== "table") throw new Error("missing table fixture");
    const duplicate = {
      entity: entity("q0", { attempted: true }),
      frequency: 7.1,
    };
    const edited: StoredParameterValue = {
      ...base,
      rows: [...base.rows, duplicate],
      rowLocations: [],
    };

    expect(
      deriveConfigDraftUpdates(config, { calibration: edited }),
    ).toEqual([
      {
        kind: "replace_parameter",
        value: edited,
      },
    ]);
  });

  it("does not treat cleared provenance as a scalar value change", () => {
    const config = testConfig();
    const edited: StoredParameterValue = {
      id: "enabled",
      shape: "scalar",
      value: true,
      metadata: {},
    };

    expect(deriveConfigDraftUpdates(config, { enabled: edited })).toEqual([]);
  });
});

function testConfig(): ConfigProfileSnapshot {
  const entities = [entity("q0"), entity("q1"), entity("q2")];
  return {
    id: "active",
    system: {
      id: "system",
      primaryEntityId: "q0",
      topology: {
        entities,
        devices: [],
        links: [],
        lines: [],
        channels: [],
        groups: [],
      },
      instruments: [],
      routing: [],
      parameterCatalog: {
        id: "parameters",
        definitions: [
          {
            id: "enabled",
            valueType: {
              shape: "scalar",
              atom: { type: "bool", nullable: false },
            },
            metadata: {},
          },
          {
            id: "calibration",
            valueType: {
              shape: "table",
              columns: [
                {
                  id: "entity",
                  valueType: {
                    type: "entity",
                    entityKind: "logical_qubit",
                    nullable: false,
                  },
                  required: true,
                },
                {
                  id: "frequency",
                  valueType: {
                    type: "float",
                    nullable: false,
                    finite: true,
                  },
                  required: true,
                },
              ],
              primaryKey: ["entity"],
              minRows: 0,
            },
            metadata: {},
          },
          {
            id: "flags",
            valueType: {
              shape: "table",
              columns: [
                {
                  id: "name",
                  valueType: {
                    type: "string",
                    nullable: false,
                    minLength: 1,
                  },
                  required: true,
                },
                {
                  id: "enabled",
                  valueType: { type: "bool", nullable: false },
                  required: true,
                },
              ],
              primaryKey: [],
              minRows: 0,
            },
            metadata: {},
          },
        ],
        metadata: {},
      },
    },
    environment: {
      id: "bench",
      connections: [],
    },
    parameterSnapshot: {
      id: "parameters",
      values: [
        {
          id: "enabled",
          shape: "scalar",
          value: true,
          sourceLocation: { uri: "old.json", path: [] },
          metadata: {},
        },
        {
          id: "calibration",
          shape: "table",
          rows: [
            {
              entity: entity("q0", { display: "base label" }),
              frequency: 6.5,
            },
            {
              entity: entity("q1"),
              frequency: 6.7,
            },
          ],
          rowLocations: [],
          metadata: {},
        },
        {
          id: "flags",
          shape: "table",
          rows: [{ name: "drive", enabled: true }],
          rowLocations: [],
          metadata: { owner: "lab" },
        },
      ],
      metadata: {},
    },
    raw: {},
  };
}

function entity(
  id: string,
  metadata: Record<string, string | boolean> = {},
): ParameterEntity {
  return {
    id,
    kind: "logical_qubit",
    metadata,
  };
}

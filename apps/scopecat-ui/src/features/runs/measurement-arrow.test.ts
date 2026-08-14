import {
  Float64,
  Int64,
  LargeBinary,
  Schema,
  Table,
  Utf8,
  tableToIPC,
  vectorFromArray,
} from "apache-arrow";
import { describe, expect, it } from "vitest";
import { decodeMeasurementArrowRecord } from "./measurement-arrow";

const json = new TextEncoder().encode("{}");

describe("live measurement Arrow", () => {
  it("decodes scalar coordinates and waveform arrays from native Arrow columns", () => {
    const base = new Table({
      "__scopecat.logical_point_id": vectorFromArray(["point-7"], new Utf8()),
      "__scopecat.point_index": vectorFromArray([7n], new Int64()),
      "__scopecat.record_metadata": vectorFromArray([json], new LargeBinary()),
      "value:bias": vectorFromArray([0.25], new Float64()),
      "unavailable_reason:bias": vectorFromArray([null], new Utf8()),
      "value_shape:bias": vectorFromArray([null]),
      "metadata:bias": vectorFromArray([json], new LargeBinary()),
      "evidence:bias": vectorFromArray([null]),
      "value:trace": vectorFromArray([[1, 2, 3]]),
      "unavailable_reason:trace": vectorFromArray([null], new Utf8()),
      "value_shape:trace": vectorFromArray([[3]]),
      "metadata:trace": vectorFromArray([json], new LargeBinary()),
      "evidence:trace": vectorFromArray([null]),
    });
    const fields = base.schema.fields.map((field) => {
      if (field.name === "value:bias") {
        return field.clone({
          metadata: new Map([
            ["scopecat.variable_role", "coordinate"],
            ["scopecat.variable_dtype", "float64"],
            ["scopecat.variable_kind", "scalar"],
            ["scopecat.variable_unit", "V"],
          ]),
        });
      }
      if (field.name === "value:trace") {
        return field.clone({
          metadata: new Map([
            ["scopecat.variable_role", "observable"],
            ["scopecat.variable_dtype", "float64"],
            ["scopecat.variable_kind", "array"],
            ["scopecat.variable_unit", "V"],
          ]),
        });
      }
      return field;
    });
    const table = new Table(
      new Schema(fields, new Map([["scopecat.run_id", "run-arrow"]])),
      base.batches,
    );
    const content = tableToIPC(table, "file");

    expect(decodeMeasurementArrowRecord(content.slice().buffer)).toMatchObject({
      run_id: "run-arrow",
      logical_point_id: "point-7",
      point_index: 7,
      coordinates: {
        bias: { kind: "scalar", dtype: "float64", unit: "V", value: 0.25 },
      },
      observables: {
        trace: {
          kind: "array",
          dtype: "float64",
          unit: "V",
          shape: [3],
          values: [1, 2, 3],
        },
      },
    });
  });
});

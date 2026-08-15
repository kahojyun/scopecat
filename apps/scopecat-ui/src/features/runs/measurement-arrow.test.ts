import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { decodeMeasurementArrowRecord } from "./measurement-arrow";

const fixture = readFileSync(
  new URL("./test-fixtures/measurement-append-v9.arrow", import.meta.url),
);

describe("live measurement Arrow", () => {
  it("decodes the current Python v9 wire including evidence and array sidecars", () => {
    const content = fixture.buffer.slice(
      fixture.byteOffset,
      fixture.byteOffset + fixture.byteLength,
    );

    expect(decodeMeasurementArrowRecord(content)).toEqual({
      run_id: "run-arrow-v9",
      logical_point_id: "point-7",
      point_index: 7,
      coordinates: {
        bias: {
          kind: "scalar",
          dtype: "float64",
          unit: "V",
          value: 0.25,
          metadata: { source: "setpoint" },
        },
      },
      observables: {
        trace: {
          kind: "array",
          dtype: "float64",
          unit: "V",
          shape: [2],
          values: [1.5, 0],
          availability: {
            valid: [true, false],
            unavailable: [
              {
                reason: "invalid",
                flat_indices: [1],
                metadata: { sample: 1 },
              },
            ],
          },
          metadata: { channel: 1 },
        },
        entity_trace: {
          kind: "segmented_array",
          dtype: "float64",
          unit: "V",
          segments: [
            {
              kind: "array",
              dtype: "float64",
              unit: "V",
              shape: [2],
              values: [4, 0],
              availability: {
                valid: [true, false],
                unavailable: [
                  {
                    reason: "overload",
                    flat_indices: [1],
                    metadata: { entity: "q0" },
                  },
                ],
              },
              metadata: { entity: "q0" },
            },
            {
              kind: "unavailable",
              reason: "missing",
              dtype: "float64",
              unit: "V",
              shape: [null],
              metadata: { entity: "q1" },
            },
          ],
          metadata: { layout: "entity-ragged" },
        },
        missing: {
          kind: "unavailable",
          reason: "overload",
          dtype: "float64",
          unit: "V",
          shape: [null],
          metadata: { status_register: 4 },
        },
      },
      acquisition_evidence: {
        events: [
          {
            command_id: "collect-readout",
            instrument_id: "scope",
            interface_id: "test.waveform/v1",
            component_path: ["channel", "1"],
            acquisition_id: "readout-0",
            started_at: "2026-08-15T09:30:00Z",
            completed_at: "2026-08-15T09:30:01Z",
          },
        ],
        entries: [
          {
            kind: "entity",
            dimension_id: "qubit",
            acquisition: { policy: "best_effort", cohort_id: "readout-batch" },
            values: [{ kind: "instrument", event_index: 0, result_id: "q0" }, null],
          },
          { kind: "instrument", event_index: 0, result_id: "trace" },
        ],
        variable_refs: { entity_trace: 0, trace: 1 },
      },
      metadata: { note: "Python Arrow v9 fixture" },
    });
  });
});

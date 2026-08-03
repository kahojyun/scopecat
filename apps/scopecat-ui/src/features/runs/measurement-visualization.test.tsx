// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MeasurementDatasetSchema } from "../../api-contract";
import { MeasurementDataPreview } from "./MeasurementDataPreview";
import { measurementTable, planMeasurementCharts } from "./measurement-visualization";

describe("measurement visualization", () => {
  it("plans a labeled scalar line from point coordinates", () => {
    const schema = scalarSchema();
    const items = [0, 1, 2].map((point) => ({
      point_index: point,
      coordinates: { bias: scalar(point * 0.1, "V") },
      observables: { signal: scalar(point + 1, "ratio") },
    }));

    expect(planMeasurementCharts(items, schema)).toEqual([
      expect.objectContaining({
        kind: "line",
        title: "Response",
        xLabel: "Bias [V]",
        yLabel: "Response [ratio]",
        series: [
          expect.objectContaining({
            points: [
              { x: 0, y: 1 },
              { x: 0.1, y: 2 },
              { x: 0.2, y: 3 },
            ],
          }),
        ],
      }),
    ]);
    expect(measurementTable(items, schema).rows[1]?.cells).toEqual(["1", "0.1 V", "2 ratio"]);
  });

  it("plans point-local complex traces as explicit magnitude series", () => {
    const schema = traceSchema();
    const items = [0, 1].map((point) => ({
      point_index: point,
      coordinates: {
        bias: scalar(point, "V"),
        frequency: array([4, 5, 6], "GHz"),
      },
      observables: {
        response: complexArray([
          { real: 3, imag: 4 },
          { real: 0, imag: 2 },
          { real: 1, imag: 0 },
        ]),
      },
    }));

    const [chart] = planMeasurementCharts(items, schema);
    expect(chart).toMatchObject({
      kind: "line",
      title: "S21 magnitude",
      xLabel: "Frequency [GHz]",
      yLabel: "|S21| [ratio]",
      note: "Complex values are shown as magnitude.",
    });
    expect(chart?.series).toHaveLength(2);
    expect(chart?.series[0]?.points).toEqual([
      { x: 4, y: 5 },
      { x: 5, y: 2 },
      { x: 6, y: 1 },
    ]);
  });

  it("keeps unsupported and malformed shapes in the table without throwing", () => {
    const schema: MeasurementDatasetSchema = {
      ...baseSchema(),
      dimensions: [
        { id: "point", kind: "point", size: 1 },
        { id: "row", kind: "sample", size: 2 },
        { id: "column", kind: "sample", size: 2 },
      ],
      variables: [
        {
          id: "image",
          role: "observable",
          dtype: "float64",
          dims: ["point", "row", "column"],
        },
      ],
      primary_observables: ["image"],
    };
    const items = [
      {
        point_index: 0,
        coordinates: {},
        observables: {
          image: { kind: "array", dtype: "float64", shape: [2, 2], values: [[1], [2, 3]] },
        },
      },
    ];

    expect(() => planMeasurementCharts(items, schema)).not.toThrow();
    expect(planMeasurementCharts(items, schema)).toEqual([]);
    expect(measurementTable(items, schema).rows[0]?.cells).toEqual(["0", "2 × 2 samples"]);
  });

  it("renders plots and a typed table while keeping raw JSON secondary", () => {
    render(
      <MeasurementDataPreview
        preview={{
          schema: scalarSchema(),
          items: [
            {
              point_index: 0,
              coordinates: { bias: scalar(0, "V") },
              observables: { signal: scalar(1, "ratio") },
            },
            {
              point_index: 1,
              coordinates: { bias: scalar(1, "V") },
              observables: { signal: scalar(2, "ratio") },
            },
          ],
        }}
        hasMore={false}
        loadingMore={false}
        onLoadMore={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("img", { name: "Response: Response [ratio] by Bias [V]" }),
    ).toBeVisible();
    expect(screen.getByRole("columnheader", { name: /Bias \[V\]/ })).toBeVisible();
    expect(screen.getByText("Raw records")).toBeVisible();
    expect(screen.getByTestId("measurement-preview")).not.toBeVisible();
  });
});

function baseSchema(): MeasurementDatasetSchema {
  return {
    format_version: "scopecat.measurement_dataset_schema.v6",
    dataset_id: "raw-measurements",
    record_schema: "scopecat.measurement_record.v4",
    dimensions: [{ id: "point", kind: "point", size: 3 }],
    variables: [],
  };
}

function scalarSchema(): MeasurementDatasetSchema {
  return {
    ...baseSchema(),
    variables: [
      {
        id: "bias",
        label: "Bias",
        role: "coordinate",
        dtype: "float64",
        unit: "V",
        dims: ["point"],
      },
      {
        id: "signal",
        label: "Response",
        role: "observable",
        dtype: "float64",
        unit: "ratio",
        dims: ["point"],
      },
    ],
    primary_coordinates: ["bias"],
    primary_observables: ["signal"],
  };
}

function traceSchema(): MeasurementDatasetSchema {
  return {
    ...baseSchema(),
    dimensions: [
      { id: "point", kind: "point", size: 2 },
      { id: "sample", kind: "sample", size: 3 },
    ],
    variables: [
      {
        id: "bias",
        label: "Bias",
        role: "coordinate",
        dtype: "float64",
        unit: "V",
        dims: ["point"],
      },
      {
        id: "frequency",
        label: "Frequency",
        role: "coordinate",
        dtype: "float64",
        unit: "GHz",
        dims: ["point", "sample"],
        recording_group_id: "readout",
      },
      {
        id: "response",
        label: "S21",
        role: "observable",
        dtype: "complex128",
        unit: "ratio",
        dims: ["point", "sample"],
        recording_group_id: "readout",
      },
    ],
    primary_coordinates: ["bias", "frequency"],
    primary_observables: ["response"],
  };
}

function scalar(value: number, unit: string) {
  return { kind: "scalar", dtype: "float64", unit, value };
}

function array(values: number[], unit: string) {
  return { kind: "array", dtype: "float64", unit, shape: [values.length], values };
}

function complexArray(values: Array<{ real: number; imag: number }>) {
  return {
    kind: "array",
    dtype: "complex128",
    unit: "ratio",
    shape: [values.length],
    values,
  };
}

// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  MeasurementDatasetSchema,
  MeasurementRecord,
  MeasurementValue,
} from "../../api-contract";
import { MeasurementDataPreview } from "./MeasurementDataPreview";
import { measurementTable, planMeasurementCharts } from "./measurement-visualization";

afterEach(cleanup);

describe("measurement visualization", () => {
  it("plans a labeled scalar line from point coordinates", () => {
    const schema = scalarSchema();
    const items = [0, 1, 2].map((point) =>
      record(point, { bias: scalar(point * 0.1, "V") }, { signal: scalar(point + 1, "ratio") }),
    );

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
    const items = [0, 1].map((point) =>
      record(
        point,
        {
          bias: scalar(point, "V"),
          frequency: array([4, 5, 6], "GHz"),
        },
        {
          response: complexArray([
            { real: 3, imag: 4 },
            { real: 0, imag: 2 },
            { real: 1, imag: 0 },
          ]),
        },
      ),
    );

    const charts = planMeasurementCharts(items, schema);
    const [chart] = charts;
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
    expect(charts.map((candidate) => candidate.title)).toEqual([
      "S21 magnitude",
      "S21 phase",
      "S21 real",
      "S21 imaginary",
    ]);
    expect(charts[1]).toMatchObject({
      yLabel: "phase(S21) [rad]",
      note: "Complex values are shown as phase in radians.",
    });
    expect(charts[1]?.series[0]?.points[0]?.y).toBeCloseTo(Math.atan2(4, 3));
    expect(charts[2]?.series[0]?.points[0]?.y).toBe(3);
    expect(charts[3]?.series[0]?.points[0]?.y).toBe(4);
  });

  it("applies complex modes when a complex variable contains widened real values", () => {
    const items = [
      record(
        0,
        { bias: scalar(0, "V"), frequency: array([4, 5], "GHz") },
        { response: array([-2, 3], "ratio") },
      ),
    ];

    const charts = planMeasurementCharts(items, traceSchema());

    expect(charts[0]?.series[0]?.points.map((point) => point.y)).toEqual([2, 3]);
    expect(charts[1]?.series[0]?.points.map((point) => point.y)).toEqual([Math.PI, 0]);
    expect(charts[2]?.series[0]?.points.map((point) => point.y)).toEqual([-2, 3]);
    expect(charts[3]?.series[0]?.points.map((point) => point.y)).toEqual([0, 0]);
  });

  it("always uses scatter for a one-dimensional point cloud", () => {
    const schema: MeasurementDatasetSchema = {
      ...scalarSchema(),
      point_domain: { kind: "point_cloud", columns: [{ id: "bias" }] },
    };
    const items = [0, 1, 2].map((point) =>
      record(point, { bias: scalar(point, "V") }, { signal: scalar(point + 1, "ratio") }),
    );

    expect(planMeasurementCharts(items, schema)).toEqual([
      expect.objectContaining({
        kind: "scatter",
        xLabel: "Bias [V]",
        yLabel: "Response [ratio]",
      }),
    ]);
  });

  it("uses ordered point-cloud columns for a two-dimensional color scatter", () => {
    const schema = twoDimensionalPointCloudSchema();
    const items = [
      record(0, { x: scalar(0, "mm"), y: scalar(2, "mm") }, { temperature: scalar(10, "K") }),
      record(1, { x: scalar(1, "mm"), y: scalar(0, "mm") }, { temperature: scalar(20, "K") }),
      record(2, { x: scalar(2, "mm"), y: scalar(1, "mm") }, { temperature: scalar(30, "K") }),
    ];

    const [chart] = planMeasurementCharts(items, schema);
    expect(chart).toMatchObject({
      kind: "color-scatter",
      title: "Temperature map",
      xLabel: "X [mm]",
      yLabel: "Y [mm]",
      colorLabel: "Temperature [K]",
      series: [
        {
          points: [
            { x: 0, y: 2, color: 10 },
            { x: 1, y: 0, color: 20 },
            { x: 2, y: 1, color: 30 },
          ],
        },
      ],
    });

    render(
      <MeasurementDataPreview
        preview={{ schema, items }}
        hasMore={false}
        loadingMore={false}
        onLoadMore={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("img", {
        name: "Temperature map: Y [mm] by X [mm], colored by Temperature [K]",
      }),
    ).toBeVisible();
  });

  it("uses authored product-grid axis order and sizes for a rectangular 2x3 heatmap", () => {
    const schema = twoDimensionalGridSchema();
    const items = gridRecords((point) => scalar(point + 10, "K"));

    const [chart] = planMeasurementCharts(items, schema);
    expect(chart).toMatchObject({
      id: "heatmap:temperature:row:column:value",
      kind: "heatmap",
      title: "Temperature heatmap",
      xLabel: "Row [mm]",
      yLabel: "Column [mm]",
      colorLabel: "Temperature [K]",
      grid: { xValues: [10, 20], yValues: [1, 2, 3] },
      note: "X and Y follow the authored product-grid axis order.",
    });
    expect(chart?.series[0]?.points).toEqual([
      { x: 10, y: 1, color: 10 },
      { x: 10, y: 2, color: 11 },
      { x: 10, y: 3, color: 12 },
      { x: 20, y: 1, color: 13 },
      { x: 20, y: 2, color: 14 },
      { x: 20, y: 3, color: 15 },
    ]);

    render(
      <MeasurementDataPreview
        preview={{ schema, items }}
        hasMore={false}
        loadingMore={false}
        onLoadMore={vi.fn()}
      />,
    );
    expect(screen.getAllByTestId("heatmap-cell")).toHaveLength(6);
    expect(
      screen.getByRole("img", {
        name: "Temperature heatmap: Column [mm] by Row [mm], colored by Temperature [K]",
      }),
    ).toBeVisible();
    expect(
      screen.getByRole("option", {
        name: "Temperature heatmap — x: Row [mm] · y: Column [mm] · color: Temperature [K]",
      }),
    ).toHaveValue("heatmap:temperature:row:column:value");
  });

  it("offers every complex mode as a product-grid heatmap", () => {
    const schema = twoDimensionalGridSchema("complex128");
    const items = gridRecords((point) => complexScalar(point + 3, point + 4, "ratio"));

    const heatmaps = planMeasurementCharts(items, schema).filter(
      (chart) => chart.kind === "heatmap",
    );

    expect(heatmaps.map((chart) => chart.title)).toEqual([
      "Temperature magnitude heatmap",
      "Temperature phase heatmap",
      "Temperature real heatmap",
      "Temperature imaginary heatmap",
    ]);
    expect(heatmaps.map((chart) => chart.colorLabel)).toEqual([
      "|Temperature| [ratio]",
      "phase(Temperature) [rad]",
      "Re(Temperature) [ratio]",
      "Im(Temperature) [ratio]",
    ]);
    expect(heatmaps[0]?.series[0]?.points[0]?.color).toBe(5);
    expect(heatmaps[1]?.series[0]?.points[0]?.color).toBeCloseTo(Math.atan2(4, 3));
    expect(heatmaps[2]?.series[0]?.points[0]?.color).toBe(3);
    expect(heatmaps[3]?.series[0]?.points[0]?.color).toBe(4);
  });

  it("skips heatmaps for missing or duplicate product-grid cells", () => {
    const schema = twoDimensionalGridSchema();
    const complete = gridRecords((point) => scalar(point + 10, "K"));
    const missing = complete.slice(0, -1);
    const duplicate = [...missing, complete[4]!];

    for (const records of [missing, duplicate]) {
      const charts = planMeasurementCharts(records, schema);
      expect(charts.some((chart) => chart.kind === "heatmap")).toBe(false);
      expect(charts[0]).toMatchObject({ kind: "scatter", title: "Temperature" });
    }
  });

  it("keeps a valid unsupported rank-two value in the table", () => {
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
      record(
        0,
        {},
        {
          image: {
            kind: "array",
            dtype: "float64",
            shape: [2, 2],
            values: [
              [1, 2],
              [3, 4],
            ],
          },
        },
      ),
    ];

    expect(() => planMeasurementCharts(items, schema)).not.toThrow();
    expect(planMeasurementCharts(items, schema)).toEqual([]);
    expect(measurementTable(items, schema).rows[0]?.cells).toEqual(["0", "2 × 2 samples"]);
  });

  it("does not infer variable contracts while the optional schema is absent", () => {
    const items = [record(0, { bias: scalar(1, "V") }, { signal: scalar(2, "ratio") })];

    expect(planMeasurementCharts(items)).toEqual([]);
    expect(measurementTable(items)).toEqual({
      columns: [{ id: "point", label: "Point", role: "point" }],
      rows: [{ id: "point-0:0", cells: ["0"] }],
    });
  });

  it("renders plots and a typed table while keeping raw JSON secondary", () => {
    render(
      <MeasurementDataPreview
        preview={{
          schema: scalarSchema(),
          items: [
            record(0, { bias: scalar(0, "V") }, { signal: scalar(1, "ratio") }),
            record(1, { bias: scalar(1, "V") }, { signal: scalar(2, "ratio") }),
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

  it("offers every chart candidate instead of silently truncating observables", () => {
    const variables = Array.from({ length: 8 }, (_item, index) => ({
      id: `signal-${index}`,
      label: `Response ${index + 1}`,
      role: "observable" as const,
      dtype: "float64" as const,
      unit: "ratio",
      dims: ["point"],
    }));
    const schema: MeasurementDatasetSchema = {
      ...scalarSchema(),
      variables: [scalarSchema().variables![0]!, ...variables],
      primary_observables: variables.map((variable) => variable.id),
    };
    const items = [0, 1].map((point) =>
      record(
        point,
        { bias: scalar(point, "V") },
        Object.fromEntries(
          variables.map((variable, index) => [variable.id, scalar(point + index, "ratio")]),
        ),
      ),
    );

    render(
      <MeasurementDataPreview
        preview={{ schema, items }}
        hasMore={false}
        loadingMore={false}
        onLoadMore={vi.fn()}
      />,
    );

    const selector = screen.getByRole("combobox", { name: "Measurement chart" });
    expect(selector).toHaveValue("scalar:signal-0:bias:value");
    expect(screen.getAllByRole("option")).toHaveLength(8);
    expect(screen.getByText("8 chart candidates")).toBeVisible();

    fireEvent.change(selector, { target: { value: "scalar:signal-7:bias:value" } });
    expect(
      screen.getByRole("img", { name: "Response 8: Response 8 [ratio] by Bias [V]" }),
    ).toBeVisible();
  });
});

function baseSchema(): MeasurementDatasetSchema {
  return {
    format_version: "scopecat.measurement_dataset_schema.v7",
    dataset_id: "raw-measurements",
    record_schema: "scopecat.measurement_record.v4",
    point_domain: { kind: "product_grid", axes: [] },
    dimensions: [{ id: "point", kind: "point", size: 3 }],
    variables: [],
  };
}

function scalarSchema(): MeasurementDatasetSchema {
  return {
    ...baseSchema(),
    point_domain: { kind: "product_grid", axes: [{ id: "bias", size: 3 }] },
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
    point_domain: { kind: "product_grid", axes: [{ id: "bias", size: 2 }] },
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

function twoDimensionalPointCloudSchema(): MeasurementDatasetSchema {
  return {
    ...baseSchema(),
    point_domain: {
      kind: "point_cloud",
      columns: [{ id: "x" }, { id: "y" }],
    },
    variables: [
      {
        id: "x",
        label: "X",
        role: "coordinate",
        dtype: "float64",
        unit: "mm",
        dims: ["point"],
      },
      {
        id: "y",
        label: "Y",
        role: "coordinate",
        dtype: "float64",
        unit: "mm",
        dims: ["point"],
      },
      {
        id: "temperature",
        label: "Temperature",
        role: "observable",
        dtype: "float64",
        unit: "K",
        dims: ["point"],
      },
    ],
    primary_coordinates: ["y", "x"],
    primary_observables: ["temperature"],
  };
}

function twoDimensionalGridSchema(
  dtype: "complex128" | "float64" = "float64",
): MeasurementDatasetSchema {
  return {
    ...baseSchema(),
    dimensions: [{ id: "point", kind: "point", size: 6 }],
    point_domain: {
      kind: "product_grid",
      axes: [
        { id: "row", size: 2 },
        { id: "column", size: 3 },
      ],
    },
    variables: [
      {
        id: "column",
        label: "Column",
        role: "coordinate",
        dtype: "float64",
        unit: "mm",
        dims: ["point"],
      },
      {
        id: "row",
        label: "Row",
        role: "coordinate",
        dtype: "float64",
        unit: "mm",
        dims: ["point"],
      },
      {
        id: "temperature",
        label: "Temperature",
        role: "observable",
        dtype,
        unit: dtype === "complex128" ? "ratio" : "K",
        dims: ["point"],
      },
    ],
    primary_coordinates: ["column", "row"],
    primary_observables: ["temperature"],
  };
}

function gridRecords(observable: (point: number) => MeasurementValue): MeasurementRecord[] {
  return [10, 20].flatMap((row) =>
    [1, 2, 3].map((column, point) =>
      record(
        (row === 10 ? 0 : 3) + point,
        { column: scalar(column, "mm"), row: scalar(row, "mm") },
        { temperature: observable((row === 10 ? 0 : 3) + point) },
      ),
    ),
  );
}

function record(
  pointIndex: number,
  coordinates: Record<string, MeasurementValue>,
  observables: Record<string, MeasurementValue>,
): MeasurementRecord {
  return {
    run_id: "run-1",
    logical_point_id: `point-${pointIndex}`,
    point_index: pointIndex,
    coordinates,
    observables,
  };
}

function scalar(value: number, unit: string): Extract<MeasurementValue, { kind: "scalar" }> {
  return { kind: "scalar", dtype: "float64", unit, value };
}

function complexScalar(
  real: number,
  imag: number,
  unit: string,
): Extract<MeasurementValue, { kind: "scalar" }> {
  return { kind: "scalar", dtype: "complex128", unit, value: { real, imag } };
}

function array(values: number[], unit: string): Extract<MeasurementValue, { kind: "array" }> {
  return { kind: "array", dtype: "float64", unit, shape: [values.length], values };
}

function complexArray(
  values: Array<{ real: number; imag: number }>,
): Extract<MeasurementValue, { kind: "array" }> {
  return {
    kind: "array",
    dtype: "complex128",
    unit: "ratio",
    shape: [values.length],
    values,
  };
}

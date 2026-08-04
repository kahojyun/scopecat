import type {
  MeasurementDatasetSchema,
  MeasurementTracePreview,
  MeasurementValue,
} from "../../api-contract";

export function traceSchema(): MeasurementDatasetSchema {
  return {
    format_version: "scopecat.measurement_dataset_schema.v8",
    dataset_id: "raw-measurements",
    record_schema: "scopecat.measurement_record.v4",
    dimensions: [
      { id: "point", kind: "point", size: 2 },
      { id: "sample", kind: "sample", size: 3 },
    ],
    point_domain: {
      kind: "product_grid",
      axes: [{ id: "bias", size: 2, values: [scalar(0, "V"), scalar(1, "V")] }],
    },
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

export function realTraceSchema(): MeasurementDatasetSchema {
  const schema = traceSchema();
  return {
    ...schema,
    variables: schema.variables?.map((variable) =>
      variable.id === "response" ? { ...variable, dtype: "float64" } : variable,
    ),
  };
}

export function tracePreview(
  overrides: Partial<MeasurementTracePreview> = {},
): MeasurementTracePreview {
  return {
    coordinate_id: "frequency",
    coordinate_label: "Frequency",
    coordinate_unit: "GHz",
    dimension_id: "sample",
    downsampling: "minmax",
    observable_id: "response",
    observable_label: "S21",
    observable_unit: "ratio",
    value_mode: "magnitude",
    value_unit: "ratio",
    selected_series_count: 1,
    returned_series_count: 1,
    truncated_series: false,
    source_sample_count: 3,
    returned_sample_count: 3,
    samples_reduced: false,
    series: [traceSeries(0, [4, 5, 6], [5, 2, 1])],
    ...overrides,
  };
}

export function traceSeries(
  pointIndex: number,
  x: number[],
  y: number[],
  sourceSampleCount = y.length,
): MeasurementTracePreview["series"][number] {
  return {
    point_index: pointIndex,
    logical_point_id: `point-${pointIndex}`,
    label: `Bias ${pointIndex} V`,
    x,
    y,
    source_sample_count: sourceSampleCount,
  };
}

function scalar(value: number, unit: string): Extract<MeasurementValue, { kind: "scalar" }> {
  return { kind: "scalar", dtype: "float64", unit, value };
}

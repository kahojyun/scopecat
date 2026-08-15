import type {
  ComplexComponents,
  MeasurementDatasetSchema,
  MeasurementRecord,
  MeasurementTracePreview,
  MeasurementValue,
} from "../../api-contract";

type SchemaVariable = NonNullable<MeasurementDatasetSchema["variables"]>[number];
type ProductGridSchemaAxis = Extract<
  MeasurementDatasetSchema["point_domain"],
  { kind: "product_grid" }
>["axes"][number];
type VariableRole = SchemaVariable["role"];
type MeasurementScalar = Extract<MeasurementValue, { kind: "scalar" }>;
type MeasurementScalarValue = Extract<MeasurementValue, { kind: "scalar" }>["value"];

interface VariableDescriptor {
  id: string;
  role: VariableRole;
  dtype: SchemaVariable["dtype"];
  unit?: string;
  dims: string[];
  label: string;
  recordingGroupId?: string;
}

interface NumericPoint {
  x: number;
  y: number;
  color?: number;
}

export type NumericValueMode = "imag" | "magnitude" | "phase" | "real" | "value";

const COMPLEX_VALUE_MODES: NumericValueMode[] = ["magnitude", "phase", "real", "imag"];

export interface MeasurementChartSeries {
  id: string;
  label: string;
  points: NumericPoint[];
}

export interface MeasurementChartGrid {
  xValues: number[];
  yValues: number[];
}

interface MeasurementChartFixedCoordinateBase {
  id: string;
  label: string;
  unit?: string;
  disambiguateIndex?: boolean;
}

export type MeasurementChartFixedCoordinate = MeasurementChartFixedCoordinateBase &
  ({ value: MeasurementScalarValue; index?: number } | { value?: never; index: number });

export interface MeasurementSliceAxis {
  id: string;
  label: string;
  unit?: string;
  size: number;
  source: ProductGridSchemaAxis["source"];
}

export interface MeasurementHeatmapCapability {
  xAxis: MeasurementSliceAxis;
  yAxis: MeasurementSliceAxis;
  observableIds: string[];
}

export interface MeasurementSlicePlan {
  varyingAxes: MeasurementSliceAxis[];
  fixedAxes: MeasurementSliceAxis[];
  variableIds: string[];
  heatmap?: MeasurementHeatmapCapability;
}

export interface MeasurementTraceQueryPlan {
  id: string;
  label: string;
  observableId: string;
  coordinateId: string;
  valueMode: NumericValueMode;
}

interface MeasurementChartPlanBase {
  id: string;
  title: string;
  xLabel: string;
  yLabel: string;
  colorLabel?: string;
  note?: string;
  series: MeasurementChartSeries[];
}

export type MeasurementChartPlan = MeasurementChartPlanBase &
  (
    | {
        kind: "heatmap";
        grid: MeasurementChartGrid;
        fixedCoordinates: MeasurementChartFixedCoordinate[];
      }
    | {
        kind: "color-scatter" | "line" | "scatter";
        fixedCoordinates?: never;
        grid?: never;
      }
  );

export interface MeasurementTableColumn {
  id: string;
  label: string;
  role: "point" | VariableRole;
}

export interface MeasurementTableRow {
  id: string;
  cells: string[];
}

export interface MeasurementTableModel {
  columns: MeasurementTableColumn[];
  rows: MeasurementTableRow[];
}

/** Derive only schema-safe automatic plots; unsupported shapes remain tabular. */
export function planMeasurementCharts(
  records: MeasurementRecord[],
  schema?: MeasurementDatasetSchema,
  fixedAxisIndices?: Readonly<Record<string, number>>,
): MeasurementChartPlan[] {
  if (records.length === 0 || schema === undefined) return [];
  const variables = variableDescriptors(schema);
  const observables = orderObservables(variables, schema);
  const gridPlans = productGridHeatmaps(records, variables, observables, schema, fixedAxisIndices);
  const colorPlans = pointCloudColorCharts(records, variables, observables, schema);
  const scalarPlans = observables
    .filter((variable) => variable.dims.length === 1)
    .flatMap((observable) => scalarChart(records, variables, observable, schema));
  return [...gridPlans, ...colorPlans, ...scalarPlans];
}

/** Choose bounded server projection axes for one product-grid slice. */
export function measurementSlicePlan(
  schema?: MeasurementDatasetSchema,
): MeasurementSlicePlan | undefined {
  if (schema?.point_domain.kind !== "product_grid") return undefined;
  const variables = variableDescriptors(schema);
  const variablesById = new Map(variables.map((variable) => [variable.id, variable]));
  const axes: ProductGridAxis[] = schema.point_domain.axes.map((axis) => {
    const variable = variablesById.get(axis.id);
    return {
      axis,
      variable:
        variable && variable.role === "coordinate" && variable.dims.length === 1
          ? variable
          : undefined,
    };
  });
  if (axes.length === 0 || axes.some(({ axis }) => !validGridSize(axis.size))) return undefined;
  const numericAxes = axes.filter(hasRealNumericVariable);
  const varyingAxes = numericAxes.length > 0 ? numericAxes.slice(0, 2) : axes.slice(0, 1);
  const varyingAxisIds = new Set(varyingAxes.map(({ axis }) => axis.id));
  const observables = variables.filter(
    (variable) =>
      variable.role === "observable" && variable.dims.length === 1 && isNumericVariable(variable),
  );
  const heatmapAxes = numericAxes.slice(0, 2);
  const heatmap =
    heatmapAxes.length === 2 && observables.length > 0
      ? {
          xAxis: sliceAxisDescriptor(heatmapAxes[0]!),
          yAxis: sliceAxisDescriptor(heatmapAxes[1]!),
          observableIds: observables.map((observable) => observable.id),
        }
      : undefined;
  return {
    varyingAxes: varyingAxes.map(sliceAxisDescriptor),
    fixedAxes: axes.filter(({ axis }) => !varyingAxisIds.has(axis.id)).map(sliceAxisDescriptor),
    variableIds: [
      ...varyingAxes.flatMap(({ variable }) =>
        variable && isNumericVariable(variable) ? [variable.id] : [],
      ),
      ...observables.map((observable) => observable.id),
    ],
    heatmap,
  };
}

/** Pair aligned rank-one coordinates and observables for trace previews. */
export function measurementTraceQueryPlans(
  schema?: MeasurementDatasetSchema,
): MeasurementTraceQueryPlan[] {
  if (!schema) return [];
  const variables = variableDescriptors(schema);
  const coordinates = variables.filter(
    (variable) =>
      variable.role === "coordinate" &&
      variable.dims.length === 2 &&
      isRealNumericVariable(variable),
  );
  const observables = orderObservables(
    variables.filter(
      (variable) =>
        variable.role === "observable" && variable.dims.length === 2 && isNumericVariable(variable),
    ),
    schema,
  );
  return observables.flatMap((observable) => {
    const compatibleCoordinates = coordinates.filter(
      (coordinate) =>
        coordinate.dims.every((dimension, index) => dimension === observable.dims[index]) &&
        coordinate.recordingGroupId === observable.recordingGroupId,
    );
    return compatibleCoordinates.flatMap((coordinate) =>
      valueModes(observable).map((valueMode) => ({
        id: `trace:${observable.id}:${coordinate.id}:${valueMode}`,
        label:
          compatibleCoordinates.length === 1
            ? chartTitle(observable, valueMode)
            : `${chartTitle(observable, valueMode)} by ${coordinate.label}`,
        observableId: observable.id,
        coordinateId: coordinate.id,
        valueMode,
      })),
    );
  });
}

export function measurementTraceChart(
  preview?: MeasurementTracePreview,
): MeasurementChartPlan | undefined {
  if (!preview || preview.series.length === 0) return undefined;
  const observable: VariableDescriptor = {
    id: preview.observable_id,
    role: "observable",
    dtype: preview.value_mode === "value" ? "float64" : "complex128",
    unit: preview.value_unit ?? preview.observable_unit ?? undefined,
    dims: ["point", preview.dimension_id],
    label: preview.observable_label ?? dimensionLabel(preview.observable_id),
  };
  const series = preview.series.map((candidate) => ({
    id: candidate.logical_point_id
      ? `${candidate.logical_point_id}:${candidate.point_index}`
      : `point-${candidate.point_index}`,
    label: candidate.label,
    points: candidate.x.map((x, index) => ({ x, y: candidate.y[index]! })),
  }));
  const monotonic = preview.series.every((candidate) => strictlyMonotonicValues(candidate.x));
  return {
    id: `trace:${preview.observable_id}:${preview.coordinate_id}:${preview.value_mode}`,
    kind: monotonic ? "line" : "scatter",
    title: chartTitle(observable, preview.value_mode),
    xLabel: labelWithUnit(
      preview.coordinate_label ?? dimensionLabel(preview.coordinate_id),
      preview.coordinate_unit,
    ),
    yLabel: chartValueLabel(observable, preview.value_mode),
    note: chartNote(preview.value_mode),
    series,
  };
}

export function measurementTraceStatus(preview: MeasurementTracePreview): string {
  const series = `${preview.returned_series_count.toLocaleString()} of ${preview.selected_series_count.toLocaleString()} selected series returned`;
  const truncation = preview.truncated_series ? "series limit applied" : undefined;
  const samples = preview.samples_reduced
    ? `${preview.returned_sample_count.toLocaleString()} of ${preview.source_sample_count.toLocaleString()} source samples plotted · evenly downsampled`
    : `${preview.returned_sample_count.toLocaleString()} source samples plotted`;
  return [series, truncation, samples].filter((item) => item !== undefined).join(" · ");
}

function sliceAxisDescriptor({ axis, variable }: ProductGridAxis): MeasurementSliceAxis {
  return {
    id: axis.id,
    label: variable?.label ?? dimensionLabel(axis.id),
    unit: variable?.unit,
    size: axis.size,
    source: axis.source,
  };
}

/** Read one compact product-grid coordinate without expanding the whole axis. */
export function measurementSliceAxisValue(
  axis: MeasurementSliceAxis,
  index: number,
): MeasurementScalar | null | undefined {
  const source = axis.source;
  if (source.kind === "values") return source.values[index];
  if (source.kind === "range") {
    return generatedScalar(
      source.start,
      interpolatedValue(
        source.start.value as number,
        source.stop.value as number,
        axis.size,
        index,
      ),
    );
  }
  const center = source.center.value as number;
  const span = source.span.value as number;
  const lastIndex = axis.size - 1;
  const value =
    index === 0
      ? center - span / 2
      : index === lastIndex
        ? center + span / 2
        : center + (span * (2 * index - lastIndex)) / (2 * lastIndex);
  return generatedScalar(source.center, value);
}

export function measurementSliceAxisValueIsDuplicated(
  axis: MeasurementSliceAxis,
  index: number,
): boolean {
  const scalar = measurementSliceAxisValue(axis, index);
  if (scalar === null || scalar === undefined) return false;
  const sameValue = (candidate: MeasurementScalar | null | undefined) =>
    candidate !== null &&
    candidate !== undefined &&
    JSON.stringify([candidate.dtype, candidate.unit, candidate.value]) ===
      JSON.stringify([scalar.dtype, scalar.unit, scalar.value]);
  if (axis.source.kind === "values") {
    return axis.source.values.some(
      (candidate, candidateIndex) => candidateIndex !== index && sameValue(candidate),
    );
  }
  return (
    (index > 0 && sameValue(measurementSliceAxisValue(axis, index - 1))) ||
    (index + 1 < axis.size && sameValue(measurementSliceAxisValue(axis, index + 1)))
  );
}

function generatedScalar(template: MeasurementScalar, value: number): MeasurementScalar {
  return { ...template, value };
}

function interpolatedValue(start: number, stop: number, size: number, index: number): number {
  if (index === 0) return start;
  if (index === size - 1) return stop;
  const difference = stop - start;
  if (Number.isFinite(difference)) return start + index * (difference / (size - 1));
  const weight = index / (size - 1);
  return start * (1 - weight) + stop * weight;
}

export function measurementTable(
  records: MeasurementRecord[],
  schema?: MeasurementDatasetSchema,
): MeasurementTableModel {
  const variables = schema ? variableDescriptors(schema) : [];
  const columns: MeasurementTableColumn[] = [
    { id: "point", label: "Point", role: "point" },
    ...variables.map((variable) => ({
      id: variable.id,
      label: valueLabel(variable),
      role: variable.role,
    })),
  ];
  return {
    columns,
    rows: records.map((record, index) => ({
      id: `${record.logical_point_id ?? record.point_index}:${index}`,
      cells: [
        String(record.point_index),
        ...variables.map((variable) => formatMeasurementValue(valueFor(record, variable))),
      ],
    })),
  };
}

function scalarChart(
  records: MeasurementRecord[],
  variables: VariableDescriptor[],
  observable: VariableDescriptor,
  schema: MeasurementDatasetSchema,
): MeasurementChartPlan[] {
  const candidates = variables.filter(
    (variable) => variable.role === "coordinate" && variable.dims.length === 1,
  );
  const coordinate = orderCoordinates(candidates, schema).find((candidate) =>
    records.some((record) => numericScalar(valueFor(record, candidate)) !== undefined),
  );
  return valueModes(observable).flatMap((mode) => {
    const points = records.flatMap((record) => {
      const y = numericScalar(valueFor(record, observable), mode);
      const x = coordinate ? numericScalar(valueFor(record, coordinate)) : record.point_index;
      return x === undefined || y === undefined ? [] : [{ x, y }];
    });
    if (points.length === 0) return [];
    return [
      {
        id: `scalar:${observable.id}:${coordinate?.id ?? "point"}:${mode}`,
        kind:
          schema.point_domain.kind === "point_cloud" || !strictlyMonotonic(points)
            ? "scatter"
            : "line",
        title: chartTitle(observable, mode),
        xLabel: coordinate ? valueLabel(coordinate) : "Point index",
        yLabel: chartValueLabel(observable, mode),
        note: chartNote(mode),
        series: [{ id: observable.id, label: observable.label, points }],
      },
    ];
  });
}

function productGridHeatmaps(
  records: MeasurementRecord[],
  variables: VariableDescriptor[],
  observables: VariableDescriptor[],
  schema: MeasurementDatasetSchema,
  fixedAxisIndices?: Readonly<Record<string, number>>,
): MeasurementChartPlan[] {
  if (schema.point_domain.kind !== "product_grid") return [];
  const heatmap = measurementSlicePlan(schema)?.heatmap;
  if (!heatmap) return [];
  const variablesById = new Map(variables.map((variable) => [variable.id, variable]));
  const axes: ProductGridAxis[] = schema.point_domain.axes.map((axis) => {
    const variable = variablesById.get(axis.id);
    return {
      axis,
      variable:
        variable && variable.role === "coordinate" && variable.dims.length === 1
          ? variable
          : undefined,
    };
  });
  const xAxis = axes.find(({ axis }) => axis.id === heatmap.xAxis.id);
  const yAxis = axes.find(({ axis }) => axis.id === heatmap.yAxis.id);
  if (!xAxis || !yAxis) return [];
  if (!hasRealNumericVariable(xAxis) || !hasRealNumericVariable(yAxis)) return [];
  const fixedAxes = axes.filter((axis) => axis !== xAxis && axis !== yAxis);
  const selectedCoordinates = selectedFixedCoordinates(fixedAxes, fixedAxisIndices ?? {});
  if (selectedCoordinates === undefined) return [];

  const heatmapObservableIds = new Set(heatmap.observableIds);
  return observables
    .filter((observable) => heatmapObservableIds.has(observable.id))
    .flatMap((observable) =>
      valueModes(observable).flatMap((mode) =>
        [{ records, fixedCoordinates: selectedCoordinates }].flatMap((slice) => {
          const grid = completeGrid(
            slice.records,
            xAxis.variable,
            yAxis.variable,
            observable,
            mode,
            xAxis.axis.size,
            yAxis.axis.size,
          );
          if (!grid) return [];
          const fixedCoordinates = slice.fixedCoordinates;
          return [
            {
              id: heatmapId(observable, xAxis.variable, yAxis.variable, mode, fixedCoordinates),
              kind: "heatmap" as const,
              title: `${chartTitle(observable, mode)} heatmap`,
              xLabel: valueLabel(xAxis.variable),
              yLabel: valueLabel(yAxis.variable),
              colorLabel: chartValueLabel(observable, mode),
              fixedCoordinates,
              grid: { xValues: grid.xValues, yValues: grid.yValues },
              note: productGridNote(mode),
              series: [{ id: observable.id, label: observable.label, points: grid.points }],
            },
          ];
        }),
      ),
    );
}

interface ProductGridAxis {
  axis: ProductGridSchemaAxis;
  variable?: VariableDescriptor;
}

function selectedFixedCoordinates(
  axes: ProductGridAxis[],
  fixedAxisIndices: Readonly<Record<string, number>>,
): MeasurementChartFixedCoordinate[] | undefined {
  const selected: MeasurementChartFixedCoordinate[] = [];
  for (const { axis, variable } of axes) {
    const index = fixedAxisIndices[axis.id];
    if (index === undefined || index < 0 || index >= axis.size) return undefined;
    const descriptor = sliceAxisDescriptor({ axis, variable });
    const scalar = measurementSliceAxisValue(descriptor, index);
    selected.push(
      scalar
        ? {
            id: axis.id,
            label: variable?.label ?? dimensionLabel(axis.id),
            unit: scalar.unit ?? variable?.unit,
            value: scalar.value,
            index,
            disambiguateIndex: measurementSliceAxisValueIsDuplicated(descriptor, index),
          }
        : {
            id: axis.id,
            label: variable?.label ?? dimensionLabel(axis.id),
            index,
          },
    );
  }
  return selected;
}

function hasRealNumericVariable(
  axis: ProductGridAxis,
): axis is ProductGridAxis & { variable: VariableDescriptor } {
  return axis.variable !== undefined && isRealNumericVariable(axis.variable);
}

function heatmapId(
  observable: VariableDescriptor,
  xVariable: VariableDescriptor,
  yVariable: VariableDescriptor,
  mode: NumericValueMode,
  fixedCoordinates: MeasurementChartFixedCoordinate[],
): string {
  const base = `heatmap:${observable.id}:${xVariable.id}:${yVariable.id}:${mode}`;
  if (fixedCoordinates.length === 0) return base;
  const fixed = fixedCoordinates
    .map(
      (coordinate) =>
        `${encodeURIComponent(coordinate.id)}=${encodeURIComponent(
          [
            coordinate.value === undefined ? "opaque" : scalarValueId(coordinate.value),
            ...(coordinate.index === undefined ? [] : [`index:${coordinate.index}`]),
          ].join("@"),
        )}`,
    )
    .join("&");
  return `${base}:fixed:${fixed}`;
}

function completeGrid(
  records: MeasurementRecord[],
  xVariable: VariableDescriptor,
  yVariable: VariableDescriptor,
  observable: VariableDescriptor,
  mode: NumericValueMode,
  xSize: number,
  ySize: number,
): { points: NumericPoint[]; xValues: number[]; yValues: number[] } | undefined {
  const points: NumericPoint[] = [];
  const xValues = new Set<number>();
  const yValues = new Set<number>();
  const pairs = new Map<number, Set<number>>();
  for (const record of records) {
    const x = numericScalar(valueFor(record, xVariable));
    const y = numericScalar(valueFor(record, yVariable));
    const color = numericScalar(valueFor(record, observable), mode);
    if (x === undefined || y === undefined || color === undefined) return undefined;
    const yAtX = pairs.get(x) ?? new Set<number>();
    if (yAtX.has(y)) return undefined;
    yAtX.add(y);
    pairs.set(x, yAtX);
    xValues.add(x);
    yValues.add(y);
    points.push({ x, y, color });
  }
  if (xValues.size !== xSize || yValues.size !== ySize || points.length !== xSize * ySize) {
    return undefined;
  }
  return {
    points,
    xValues: [...xValues].sort((left, right) => left - right),
    yValues: [...yValues].sort((left, right) => left - right),
  };
}

function validGridSize(size: number): boolean {
  return Number.isSafeInteger(size) && size > 0;
}

function pointCloudColorCharts(
  records: MeasurementRecord[],
  variables: VariableDescriptor[],
  observables: VariableDescriptor[],
  schema: MeasurementDatasetSchema,
): MeasurementChartPlan[] {
  if (schema.point_domain.kind !== "point_cloud") return [];
  const variablesById = new Map(variables.map((variable) => [variable.id, variable]));
  const coordinates = schema.point_domain.columns.flatMap((column) => {
    const variable = variablesById.get(column.id);
    return variable &&
      variable.role === "coordinate" &&
      variable.dims.length === 1 &&
      isNumericVariable(variable)
      ? [variable]
      : [];
  });
  const xVariable = coordinates[0];
  const yVariable = coordinates[1];
  if (!xVariable || !yVariable) return [];
  return observables
    .filter((observable) => observable.dims.length === 1 && isNumericVariable(observable))
    .flatMap((observable) =>
      valueModes(observable).flatMap((mode) => {
        const points = records.flatMap((record) => {
          const x = numericScalar(valueFor(record, xVariable));
          const y = numericScalar(valueFor(record, yVariable));
          const color = numericScalar(valueFor(record, observable), mode);
          return x === undefined || y === undefined || color === undefined ? [] : [{ x, y, color }];
        });
        if (points.length === 0) return [];
        return [
          {
            id: `color:${observable.id}:${xVariable.id}:${yVariable.id}:${mode}`,
            kind: "color-scatter" as const,
            title: `${chartTitle(observable, mode)} map`,
            xLabel: valueLabel(xVariable),
            yLabel: valueLabel(yVariable),
            colorLabel: chartValueLabel(observable, mode),
            note: chartNote(mode),
            series: [{ id: observable.id, label: observable.label, points }],
          },
        ];
      }),
    );
}

function variableDescriptors(schema: MeasurementDatasetSchema): VariableDescriptor[] {
  return (schema.variables ?? []).map(schemaVariable);
}

function schemaVariable(variable: SchemaVariable): VariableDescriptor {
  return {
    id: variable.id,
    role: variable.role,
    dtype: variable.dtype,
    unit: variable.unit ?? undefined,
    dims: [...variable.dims],
    label: variable.label ?? dimensionLabel(variable.id),
    recordingGroupId: variable.recording_group_id ?? undefined,
  };
}

function orderObservables(
  variables: VariableDescriptor[],
  schema: MeasurementDatasetSchema,
): VariableDescriptor[] {
  const observables = variables.filter((variable) => variable.role === "observable");
  const primary = new Map((schema.primary_observables ?? []).map((id, index) => [id, index]));
  return [...observables].sort(
    (left, right) =>
      (primary.get(left.id) ?? Number.MAX_SAFE_INTEGER) -
      (primary.get(right.id) ?? Number.MAX_SAFE_INTEGER),
  );
}

function orderCoordinates(
  variables: VariableDescriptor[],
  schema: MeasurementDatasetSchema,
): VariableDescriptor[] {
  const domainIds =
    schema.point_domain.kind === "product_grid"
      ? schema.point_domain.axes.map((axis) => axis.id)
      : schema.point_domain.columns.map((column) => column.id);
  const orderedIds = [...new Set([...domainIds, ...(schema.primary_coordinates ?? [])])];
  const primary = new Map(orderedIds.map((id, index) => [id, index]));
  return [...variables].sort(
    (left, right) =>
      (primary.get(left.id) ?? Number.MAX_SAFE_INTEGER) -
      (primary.get(right.id) ?? Number.MAX_SAFE_INTEGER),
  );
}

function isNumericVariable(variable: VariableDescriptor): boolean {
  return (
    variable.dtype === "float64" || variable.dtype === "int64" || variable.dtype === "complex128"
  );
}

function isRealNumericVariable(variable: VariableDescriptor): boolean {
  return variable.dtype === "float64" || variable.dtype === "int64";
}

function valueFor(
  record: MeasurementRecord,
  variable: VariableDescriptor,
): MeasurementValue | undefined {
  return variable.role === "coordinate"
    ? record.coordinates[variable.id]
    : record.observables[variable.id];
}

function numericScalar(
  value: MeasurementValue | undefined,
  mode: NumericValueMode = "value",
): number | undefined {
  return value?.kind === "scalar" ? numericLeaf(value.value, mode) : undefined;
}

function scalarValueId(value: MeasurementScalarValue): string {
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value !== "object") return String(value);
  return `${value.real}${value.imag < 0 ? "" : "+"}${value.imag}i`;
}

function numericLeaf(value: unknown, mode: NumericValueMode): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) {
    if (mode === "magnitude") return Math.abs(value);
    if (mode === "phase") return Math.atan2(0, value);
    if (mode === "imag") return 0;
    return value;
  }
  const complex = complexComponents(value);
  if (!complex) return undefined;
  if (mode === "phase") return Math.atan2(complex.imag, complex.real);
  if (mode === "real") return complex.real;
  if (mode === "imag") return complex.imag;
  return Math.hypot(complex.real, complex.imag);
}

function complexComponents(value: unknown): ComplexComponents | undefined {
  if (
    !isObject(value) ||
    typeof value.real !== "number" ||
    !Number.isFinite(value.real) ||
    typeof value.imag !== "number" ||
    !Number.isFinite(value.imag)
  ) {
    return undefined;
  }
  return { real: value.real, imag: value.imag };
}

function formatMeasurementValue(value: MeasurementValue | undefined): string {
  if (!value) return "—";
  if (value.kind === "unavailable") return `Unavailable · ${value.reason}`;
  if (value.kind === "array") {
    const size = value.shape.length > 0 ? value.shape.join(" × ") : "?";
    return `${size} samples${unitSuffix(value.unit)}`;
  }
  if (value.kind === "segmented_array") {
    return `${value.segments.length} entity segments${unitSuffix(value.unit)}`;
  }
  return `${formatScalar(value.value)}${unitSuffix(value.unit)}`;
}

function formatScalar(value: unknown): string {
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "boolean") return value ? "True" : "False";
  if (typeof value === "string") return value;
  const complex = complexComponents(value);
  if (complex) {
    const sign = complex.imag < 0 ? "−" : "+";
    return `${formatNumber(complex.real)} ${sign} ${formatNumber(Math.abs(complex.imag))}i`;
  }
  return "—";
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumSignificantDigits: 6 }).format(value);
}

function valueLabel(variable: VariableDescriptor, magnitude = false): string {
  const label = magnitude ? `|${variable.label}|` : variable.label;
  return labelWithUnit(label, variable.unit);
}

function labelWithUnit(label: string, unit?: string | null): string {
  return `${label}${unit ? ` [${unit}]` : ""}`;
}

function valueModes(variable: VariableDescriptor): NumericValueMode[] {
  return variable.dtype === "complex128" ? COMPLEX_VALUE_MODES : ["value"];
}

function chartTitle(variable: VariableDescriptor, mode: NumericValueMode): string {
  if (mode === "value") return variable.label;
  return `${variable.label} ${mode === "imag" ? "imaginary" : mode}`;
}

function chartValueLabel(variable: VariableDescriptor, mode: NumericValueMode): string {
  if (mode === "magnitude") return valueLabel(variable, true);
  if (mode === "phase") return `phase(${variable.label}) [rad]`;
  if (mode === "real") return `Re(${variable.label})${variable.unit ? ` [${variable.unit}]` : ""}`;
  if (mode === "imag") return `Im(${variable.label})${variable.unit ? ` [${variable.unit}]` : ""}`;
  return valueLabel(variable);
}

function chartNote(mode: NumericValueMode): string | undefined {
  if (mode === "magnitude") return "Complex values are shown as magnitude.";
  if (mode === "phase") return "Complex values are shown as phase in radians.";
  if (mode === "real") return "Complex values are shown as the real component.";
  if (mode === "imag") return "Complex values are shown as the imaginary component.";
  return undefined;
}

function productGridNote(mode: NumericValueMode): string {
  const valueNote = chartNote(mode);
  const axisNote = "X and Y follow the authored product-grid axis order.";
  return valueNote ? `${valueNote} ${axisNote}` : axisNote;
}

function unitSuffix(unit?: string | null): string {
  return unit ? ` ${unit}` : "";
}

function dimensionLabel(id: string): string {
  return id.replaceAll(/[-_/]+/g, " ").replaceAll(/\b\w/g, (letter) => letter.toLocaleUpperCase());
}

function strictlyMonotonic(points: NumericPoint[]): boolean {
  return strictlyMonotonicValues(points.map((point) => point.x));
}

function strictlyMonotonicValues(values: number[]): boolean {
  if (values.length < 2) return false;
  let direction = 0;
  for (let index = 1; index < values.length; index += 1) {
    const previous = values[index - 1];
    const current = values[index];
    if (previous === undefined || current === undefined || current === previous) return false;
    const nextDirection = current > previous ? 1 : -1;
    if (direction !== 0 && direction !== nextDirection) return false;
    direction = nextDirection;
  }
  return true;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

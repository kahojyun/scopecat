import type {
  ComplexComponents,
  MeasurementDatasetSchema,
  MeasurementRecord,
  MeasurementValue,
} from "../../api-contract";

type SchemaVariable = NonNullable<MeasurementDatasetSchema["variables"]>[number];
type ProductGridSchemaAxis = Extract<
  MeasurementDatasetSchema["point_domain"],
  { kind: "product_grid" }
>["axes"][number];
type VariableRole = SchemaVariable["role"];
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

type NumericValueMode = "imag" | "magnitude" | "phase" | "real" | "value";

const COMPLEX_VALUE_MODES: NumericValueMode[] = ["magnitude", "phase", "real", "imag"];
const MAX_AUTO_HEATMAP_SLICES = 32;
const MAX_AUTO_TRACE_SERIES = 32;
const MAX_AUTO_TRACE_POINTS = 4096;

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

export interface MeasurementGridSliceAxis {
  id: string;
  label: string;
  unit?: string;
  size: number;
  values: ProductGridSchemaAxis["values"];
}

export interface MeasurementGridQueryPlan {
  xAxis: MeasurementGridSliceAxis;
  yAxis: MeasurementGridSliceAxis;
  fixedAxes: MeasurementGridSliceAxis[];
  variableIds: string[];
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
  const tracePlans = observables
    .filter((variable) => variable.dims.length === 2)
    .flatMap((observable) => traceChart(records, variables, observable));
  return [...gridPlans, ...colorPlans, ...scalarPlans, ...tracePlans];
}

export function measurementGridQuery(
  schema?: MeasurementDatasetSchema,
): MeasurementGridQueryPlan | undefined {
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
  if (axes.some(({ axis }) => !validGridSize(axis.size))) return undefined;
  const numeric = axes.filter(hasRealNumericVariable);
  const xAxis = numeric[0];
  const yAxis = numeric[1];
  if (!xAxis || !yAxis) return undefined;
  const observables = variables.filter(
    (variable) =>
      variable.role === "observable" && variable.dims.length === 1 && isNumericVariable(variable),
  );
  if (observables.length === 0) return undefined;
  return {
    xAxis: gridSliceAxisDescriptor(xAxis),
    yAxis: gridSliceAxisDescriptor(yAxis),
    fixedAxes: axes.filter((axis) => axis !== xAxis && axis !== yAxis).map(gridSliceAxisDescriptor),
    variableIds: [
      xAxis.variable.id,
      yAxis.variable.id,
      ...observables.map((observable) => observable.id),
    ],
  };
}

export function measurementGridSliceRecords(
  records: MeasurementRecord[],
  schema: MeasurementDatasetSchema,
  fixedAxisIndices: Readonly<Record<string, number>>,
): MeasurementRecord[] {
  if (schema.point_domain.kind !== "product_grid") return records;
  const axes = schema.point_domain.axes;
  const selectors = axes.flatMap((axis, axisIndex) => {
    const selectedIndex = fixedAxisIndices[axis.id];
    if (selectedIndex === undefined) return [];
    const stride = axes
      .slice(axisIndex + 1)
      .reduce((value, following) => value * following.size, 1);
    return [{ selectedIndex, size: axis.size, stride }];
  });
  return records.filter((record) =>
    selectors.every(
      ({ selectedIndex, size, stride }) =>
        Math.floor(record.point_index / stride) % size === selectedIndex,
    ),
  );
}

function gridSliceAxisDescriptor({ axis, variable }: ProductGridAxis): MeasurementGridSliceAxis {
  return {
    id: axis.id,
    label: variable?.label ?? dimensionLabel(axis.id),
    unit: variable?.unit,
    size: axis.size,
    values: axis.values,
  };
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
        ...variables.map((variable) =>
          formatMeasurementValue(valueFor(record, variable), variable.unit),
        ),
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
  if (axes.some(({ axis }) => !validGridSize(axis.size))) return [];
  const numericAxes = axes.filter(hasRealNumericVariable);
  const xAxis = numericAxes[0];
  const yAxis = numericAxes[1];
  if (!xAxis || !yAxis) return [];
  const fixedAxes = axes.filter((axis) => axis !== xAxis && axis !== yAxis);
  const selectedCoordinates =
    fixedAxisIndices === undefined
      ? undefined
      : selectedFixedCoordinates(fixedAxes, fixedAxisIndices);
  if (fixedAxisIndices !== undefined && selectedCoordinates === undefined) return [];
  const recordedFixedAxes = fixedAxes.filter(hasCoordinateVariable);
  if (fixedAxisIndices === undefined && recordedFixedAxes.length !== fixedAxes.length) return [];
  const slices = selectedCoordinates
    ? [{ records, fixedCoordinates: selectedCoordinates }]
    : productGridSlices(records, recordedFixedAxes);
  if (!slices) return [];

  return observables
    .filter((observable) => observable.dims.length === 1 && isNumericVariable(observable))
    .flatMap((observable) =>
      valueModes(observable).flatMap((mode) =>
        slices.flatMap((slice) => {
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

interface RecordedProductGridAxis extends ProductGridAxis {
  variable: VariableDescriptor;
}

interface ProductGridSlice {
  records: MeasurementRecord[];
  fixedCoordinates: MeasurementChartFixedCoordinate[];
}

function productGridSlices(
  records: MeasurementRecord[],
  fixedAxes: RecordedProductGridAxis[],
): ProductGridSlice[] | undefined {
  if (fixedAxes.length === 0) return [{ records, fixedCoordinates: [] }];
  const distinctValues = fixedAxes.map(() => new Set<string>());
  const groups = new Map<string, ProductGridSlice>();
  for (const record of records) {
    const values: MeasurementScalarValue[] = [];
    const keys: string[] = [];
    for (const [index, axis] of fixedAxes.entries()) {
      const value = scalarValue(valueFor(record, axis.variable));
      if (value === undefined) return undefined;
      const key = scalarValueKey(value);
      distinctValues[index]!.add(key);
      values.push(value);
      keys.push(key);
    }
    const key = JSON.stringify(keys);
    if (!groups.has(key) && groups.size === MAX_AUTO_HEATMAP_SLICES) return undefined;
    const slice: ProductGridSlice = groups.get(key) ?? {
      records: [],
      fixedCoordinates: values.map((value, index) => {
        const axis = fixedAxes[index]!;
        return {
          id: axis.axis.id,
          label: axis.variable.label,
          unit: axis.variable.unit,
          value,
        };
      }),
    };
    slice.records.push(record);
    groups.set(key, slice);
  }
  if (distinctValues.some((values, index) => values.size > fixedAxes[index]!.axis.size)) {
    return undefined;
  }
  return [...groups.values()];
}

function selectedFixedCoordinates(
  axes: ProductGridAxis[],
  fixedAxisIndices: Readonly<Record<string, number>>,
): MeasurementChartFixedCoordinate[] | undefined {
  const selected: MeasurementChartFixedCoordinate[] = [];
  for (const { axis, variable } of axes) {
    const index = fixedAxisIndices[axis.id];
    if (index === undefined || index < 0 || index >= axis.size) return undefined;
    const scalar = axis.values[index];
    selected.push(
      scalar
        ? {
            id: axis.id,
            label: variable?.label ?? dimensionLabel(axis.id),
            unit: scalar.unit ?? variable?.unit,
            value: scalar.value,
            index,
            disambiguateIndex: axis.values.some(
              (candidate, candidateIndex) =>
                candidateIndex !== index &&
                candidate !== null &&
                JSON.stringify([candidate.dtype, candidate.unit, candidate.value]) ===
                  JSON.stringify([scalar.dtype, scalar.unit, scalar.value]),
            ),
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

function hasCoordinateVariable(axis: ProductGridAxis): axis is RecordedProductGridAxis {
  return axis.variable !== undefined;
}

function hasRealNumericVariable(axis: ProductGridAxis): axis is RecordedProductGridAxis {
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

function traceChart(
  records: MeasurementRecord[],
  variables: VariableDescriptor[],
  observable: VariableDescriptor,
): MeasurementChartPlan[] {
  const coordinate = traceCoordinate(variables, observable);
  return valueModes(observable).flatMap((mode) => {
    const candidates: Array<{
      id: string;
      label: string;
      x: number[];
      y: number[];
    }> = [];
    for (const [index, record] of records.entries()) {
      if (candidates.length === MAX_AUTO_TRACE_SERIES) break;
      const y = numericArray(valueFor(record, observable), mode);
      if (!y || y.length === 0) continue;
      const candidateX = coordinate ? numericArray(valueFor(record, coordinate)) : undefined;
      const x = candidateX?.length === y.length ? candidateX : y.map((_value, item) => item);
      candidates.push({
        id: `${record.logical_point_id ?? record.point_index}:${index}`,
        label: traceSeriesLabel(record, variables),
        x,
        y,
      });
    }
    const pointLimit = Math.max(
      2,
      Math.floor(MAX_AUTO_TRACE_POINTS / Math.max(1, candidates.length)),
    );
    const tracesAreMonotonic = candidates.every((candidate) =>
      strictlyMonotonicValues(candidate.x),
    );
    let samplesReduced = false;
    const series = candidates.map((candidate) => {
      samplesReduced ||= candidate.y.length > pointLimit;
      return {
        id: candidate.id,
        label: candidate.label,
        points: downsampleTrace(candidate.x, candidate.y, pointLimit),
      };
    });
    if (series.length === 0) return [];
    const previewNotes = [
      chartNote(mode),
      records.length > MAX_AUTO_TRACE_SERIES
        ? `Automatic preview shows at most ${MAX_AUTO_TRACE_SERIES} point traces.`
        : undefined,
      samplesReduced
        ? `Trace samples are evenly downsampled to at most ${MAX_AUTO_TRACE_POINTS.toLocaleString()} plotted points.`
        : undefined,
    ].filter((note) => note !== undefined);
    return [
      {
        id: `trace:${observable.id}:${coordinate?.id ?? observable.dims[1] ?? "sample"}:${mode}`,
        kind: tracesAreMonotonic ? "line" : "scatter",
        title: chartTitle(observable, mode),
        xLabel: coordinate
          ? valueLabel(coordinate)
          : dimensionLabel(observable.dims[1] ?? "sample"),
        yLabel: chartValueLabel(observable, mode),
        note: previewNotes.length > 0 ? previewNotes.join(" ") : undefined,
        series,
      },
    ];
  });
}

function downsampleTrace(x: number[], y: number[], limit: number): NumericPoint[] {
  if (y.length <= limit) {
    return y.map((value, index) => ({ x: x[index] ?? index, y: value }));
  }
  return Array.from({ length: limit }, (_value, index) => {
    const sourceIndex = Math.round((index * (y.length - 1)) / (limit - 1));
    return { x: x[sourceIndex] ?? sourceIndex, y: y[sourceIndex]! };
  });
}

function traceCoordinate(
  variables: VariableDescriptor[],
  observable: VariableDescriptor,
): VariableDescriptor | undefined {
  const candidates = variables.filter(
    (variable) =>
      variable.role === "coordinate" &&
      variable.dims.length === 2 &&
      variable.dims.every((dimension, index) => dimension === observable.dims[index]),
  );
  return (
    candidates.find(
      (candidate) =>
        observable.recordingGroupId !== undefined &&
        candidate.recordingGroupId === observable.recordingGroupId,
    ) ?? candidates[0]
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

function scalarValue(value: MeasurementValue | undefined): MeasurementScalarValue | undefined {
  return value?.kind === "scalar" ? value.value : undefined;
}

function scalarValueKey(value: MeasurementScalarValue): string {
  if (typeof value === "boolean") return `bool:${value}`;
  if (typeof value === "number") return `number:${value}`;
  if (typeof value === "string") return `string:${value}`;
  return `complex:${value.real}:${value.imag}`;
}

function scalarValueId(value: MeasurementScalarValue): string {
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value !== "object") return String(value);
  return `${value.real}${value.imag < 0 ? "" : "+"}${value.imag}i`;
}

function numericArray(
  value: MeasurementValue | undefined,
  mode: NumericValueMode = "value",
): number[] | undefined {
  if (value?.kind !== "array" || value.shape.length !== 1) return undefined;
  const numbers: number[] = [];
  for (const leaf of value.values) {
    const numeric = numericLeaf(leaf, mode);
    if (numeric === undefined) return undefined;
    numbers.push(numeric);
  }
  return numbers;
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

function traceSeriesLabel(record: MeasurementRecord, variables: VariableDescriptor[]): string {
  const coordinates = variables
    .filter((variable) => variable.role === "coordinate" && variable.dims.length === 1)
    .flatMap((variable) => {
      const value = valueFor(record, variable);
      return value?.kind === "scalar"
        ? [
            `${variable.label} ${formatScalar(value.value)}${unitSuffix(value.unit ?? variable.unit)}`,
          ]
        : [];
    });
  return coordinates.length > 0 ? coordinates.join(" · ") : `Point ${record.point_index}`;
}

function formatMeasurementValue(
  value: MeasurementValue | undefined,
  fallbackUnit?: string,
): string {
  if (!value) return "—";
  if (value.kind === "unavailable") return `Unavailable · ${value.reason}`;
  if (value.kind === "array") {
    const size = value.shape.length > 0 ? value.shape.join(" × ") : "?";
    return `${size} samples${unitSuffix(value.unit ?? fallbackUnit)}`;
  }
  return `${formatScalar(value.value)}${unitSuffix(value.unit ?? fallbackUnit)}`;
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
  return `${label}${variable.unit ? ` [${variable.unit}]` : ""}`;
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

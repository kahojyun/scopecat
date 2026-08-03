import type {
  ComplexComponents,
  MeasurementDatasetSchema,
  MeasurementRecord,
  MeasurementValue,
} from "../../api-contract";

type SchemaVariable = NonNullable<MeasurementDatasetSchema["variables"]>[number];
type VariableRole = SchemaVariable["role"];

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

export interface MeasurementChartSeries {
  id: string;
  label: string;
  points: NumericPoint[];
}

export interface MeasurementChartGrid {
  xValues: number[];
  yValues: number[];
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
    | { kind: "heatmap"; grid: MeasurementChartGrid }
    | { kind: "color-scatter" | "line" | "scatter"; grid?: never }
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
): MeasurementChartPlan[] {
  if (records.length === 0 || schema === undefined) return [];
  const variables = variableDescriptors(schema);
  const observables = orderObservables(variables, schema);
  const gridPlans = productGridHeatmaps(records, variables, observables, schema);
  const colorPlans = pointCloudColorCharts(records, variables, observables, schema);
  const scalarPlans = observables
    .filter((variable) => variable.dims.length === 1)
    .flatMap((observable) => scalarChart(records, variables, observable, schema));
  const tracePlans = observables
    .filter((variable) => variable.dims.length === 2)
    .flatMap((observable) => traceChart(records, variables, observable));
  return [...gridPlans, ...colorPlans, ...scalarPlans, ...tracePlans];
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
): MeasurementChartPlan[] {
  if (schema.point_domain.kind !== "product_grid") return [];
  const variablesById = new Map(variables.map((variable) => [variable.id, variable]));
  const axes = schema.point_domain.axes.flatMap((axis) => {
    const variable = variablesById.get(axis.id);
    return variable &&
      variable.role === "coordinate" &&
      variable.dims.length === 1 &&
      isRealNumericVariable(variable)
      ? [{ size: axis.size, variable }]
      : [];
  });
  const xAxis = axes[0];
  const yAxis = axes[1];
  if (!xAxis || !yAxis || !validGridSize(xAxis.size) || !validGridSize(yAxis.size)) return [];
  const expectedCellCount = xAxis.size * yAxis.size;
  if (!Number.isSafeInteger(expectedCellCount) || records.length !== expectedCellCount) return [];

  return observables
    .filter((observable) => observable.dims.length === 1 && isNumericVariable(observable))
    .flatMap((observable) =>
      valueModes(observable).flatMap((mode) => {
        const grid = completeGrid(
          records,
          xAxis.variable,
          yAxis.variable,
          observable,
          mode,
          xAxis.size,
          yAxis.size,
        );
        if (!grid) return [];
        return [
          {
            id: `heatmap:${observable.id}:${xAxis.variable.id}:${yAxis.variable.id}:${mode}`,
            kind: "heatmap" as const,
            title: `${chartTitle(observable, mode)} heatmap`,
            xLabel: valueLabel(xAxis.variable),
            yLabel: valueLabel(yAxis.variable),
            colorLabel: chartValueLabel(observable, mode),
            grid: { xValues: grid.xValues, yValues: grid.yValues },
            note: productGridNote(mode),
            series: [{ id: observable.id, label: observable.label, points: grid.points }],
          },
        ];
      }),
    );
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
    const series = records.flatMap((record, index) => {
      const y = numericArray(valueFor(record, observable), mode);
      if (!y || y.length === 0) return [];
      const candidateX = coordinate ? numericArray(valueFor(record, coordinate)) : undefined;
      const x = candidateX?.length === y.length ? candidateX : y.map((_value, item) => item);
      return [
        {
          id: `${record.logical_point_id ?? record.point_index}:${index}`,
          label: traceSeriesLabel(record, variables),
          points: y.map((value, item) => ({ x: x[item] ?? item, y: value })),
        },
      ];
    });
    if (series.length === 0) return [];
    return [
      {
        id: `trace:${observable.id}:${coordinate?.id ?? observable.dims[1] ?? "sample"}:${mode}`,
        kind: series.every((item) => strictlyMonotonic(item.points)) ? "line" : "scatter",
        title: chartTitle(observable, mode),
        xLabel: coordinate
          ? valueLabel(coordinate)
          : dimensionLabel(observable.dims[1] ?? "sample"),
        yLabel: chartValueLabel(observable, mode),
        note: chartNote(mode),
        series,
      },
    ];
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
  if (points.length < 2) return false;
  let direction = 0;
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const current = points[index];
    if (!previous || !current || current.x === previous.x) return false;
    const nextDirection = current.x > previous.x ? 1 : -1;
    if (direction !== 0 && direction !== nextDirection) return false;
    direction = nextDirection;
  }
  return true;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

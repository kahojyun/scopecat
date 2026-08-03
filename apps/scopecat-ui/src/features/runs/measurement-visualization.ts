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
}

export interface MeasurementChartSeries {
  id: string;
  label: string;
  points: NumericPoint[];
}

export interface MeasurementChartPlan {
  id: string;
  kind: "line" | "scatter";
  title: string;
  xLabel: string;
  yLabel: string;
  note?: string;
  series: MeasurementChartSeries[];
}

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
  const scalarPlans = observables
    .filter((variable) => variable.dims.length === 1)
    .flatMap((observable) => scalarChart(records, variables, observable, schema));
  const tracePlans = observables
    .filter((variable) => variable.dims.length === 2)
    .flatMap((observable) => traceChart(records, variables, observable));
  return [...scalarPlans, ...tracePlans].slice(0, 6);
}

export function measurementTable(
  records: MeasurementRecord[],
  schema?: MeasurementDatasetSchema,
): MeasurementTableModel {
  const variables = schema ? variableDescriptors(schema).slice(0, 10) : [];
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
  const points = records.flatMap((record) => {
    const y = numericScalar(valueFor(record, observable));
    const x = coordinate ? numericScalar(valueFor(record, coordinate)) : record.point_index;
    return x === undefined || y === undefined ? [] : [{ x, y }];
  });
  if (points.length === 0) return [];
  const complex = observable.dtype === "complex128";
  return [
    {
      id: `scalar:${observable.id}:${coordinate?.id ?? "point"}`,
      kind:
        pointDomainLayout(schema) === "point_cloud" || !strictlyMonotonic(points)
          ? "scatter"
          : "line",
      title: complex ? `${observable.label} magnitude` : observable.label,
      xLabel: coordinate ? valueLabel(coordinate) : "Point index",
      yLabel: valueLabel(observable, complex),
      note: complex ? "Complex values are shown as magnitude." : undefined,
      series: [{ id: observable.id, label: observable.label, points }],
    },
  ];
}

function traceChart(
  records: MeasurementRecord[],
  variables: VariableDescriptor[],
  observable: VariableDescriptor,
): MeasurementChartPlan[] {
  const coordinate = traceCoordinate(variables, observable);
  const complex = observable.dtype === "complex128";
  const series = records
    .flatMap((record, index) => {
      const y = numericArray(valueFor(record, observable));
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
    })
    .slice(-6);
  if (series.length === 0) return [];
  return [
    {
      id: `trace:${observable.id}:${coordinate?.id ?? observable.dims[1] ?? "sample"}`,
      kind: series.every((item) => strictlyMonotonic(item.points)) ? "line" : "scatter",
      title: complex ? `${observable.label} magnitude` : observable.label,
      xLabel: coordinate ? valueLabel(coordinate) : dimensionLabel(observable.dims[1] ?? "sample"),
      yLabel: valueLabel(observable, complex),
      note: complex ? "Complex values are shown as magnitude." : undefined,
      series,
    },
  ];
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
  const primary = new Map((schema.primary_coordinates ?? []).map((id, index) => [id, index]));
  return [...variables].sort(
    (left, right) =>
      (primary.get(left.id) ?? Number.MAX_SAFE_INTEGER) -
      (primary.get(right.id) ?? Number.MAX_SAFE_INTEGER),
  );
}

function valueFor(
  record: MeasurementRecord,
  variable: VariableDescriptor,
): MeasurementValue | undefined {
  return variable.role === "coordinate"
    ? record.coordinates[variable.id]
    : record.observables[variable.id];
}

function numericScalar(value: MeasurementValue | undefined): number | undefined {
  return value?.kind === "scalar" ? numericLeaf(value.value) : undefined;
}

function numericArray(value: MeasurementValue | undefined): number[] | undefined {
  if (value?.kind !== "array" || value.shape.length !== 1) return undefined;
  const numbers: number[] = [];
  for (const leaf of value.values) {
    const numeric = numericLeaf(leaf);
    if (numeric === undefined) return undefined;
    numbers.push(numeric);
  }
  return numbers;
}

function numericLeaf(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const complex = complexComponents(value);
  return complex ? Math.hypot(complex.real, complex.imag) : undefined;
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

function pointDomainLayout(schema: MeasurementDatasetSchema): string | undefined {
  const metadata = schema.metadata;
  if (!isObject(metadata)) return undefined;
  const direct = text(metadata.point_domain_layout) ?? text(metadata.domain_layout);
  if (direct) return direct;
  const domain = metadata.point_domain;
  return isObject(domain) ? (text(domain.layout) ?? text(domain.kind)) : undefined;
}

function text(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

import type { MeasurementDatasetSchema } from "../../api-contract";

type SchemaVariable = NonNullable<MeasurementDatasetSchema["variables"]>[number];
type VariableRole = "coordinate" | "observable";

interface MeasurementRecordView {
  pointIndex: number;
  coordinates: Record<string, unknown>;
  observables: Record<string, unknown>;
}

interface VariableDescriptor {
  id: string;
  role: VariableRole;
  dtype: string;
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

interface ParsedScalar {
  kind: "scalar";
  dtype?: string;
  unit?: string;
  value: unknown;
}

interface ParsedArray {
  kind: "array";
  dtype?: string;
  unit?: string;
  shape: number[];
  values: unknown;
}

interface ParsedUnavailable {
  kind: "unavailable";
  dtype?: string;
  unit?: string;
  shape: number[];
  reason: string;
}

type ParsedValue = ParsedScalar | ParsedArray | ParsedUnavailable;

export function planMeasurementCharts(
  items: Array<Record<string, unknown>>,
  schema?: MeasurementDatasetSchema,
): MeasurementChartPlan[] {
  const records = parseRecords(items);
  if (records.length === 0) return [];
  const variables = variableDescriptors(records, schema);
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
  items: Array<Record<string, unknown>>,
  schema?: MeasurementDatasetSchema,
): MeasurementTableModel {
  const records = parseRecords(items);
  const variables = variableDescriptors(records, schema).slice(0, 10);
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
      id: `${record.pointIndex}:${index}`,
      cells: [
        String(record.pointIndex),
        ...variables.map((variable) =>
          formatMeasurementValue(valueFor(record, variable), variable.unit),
        ),
      ],
    })),
  };
}

function scalarChart(
  records: MeasurementRecordView[],
  variables: VariableDescriptor[],
  observable: VariableDescriptor,
  schema?: MeasurementDatasetSchema,
): MeasurementChartPlan[] {
  const candidates = variables.filter(
    (variable) => variable.role === "coordinate" && variable.dims.length === 1,
  );
  const orderedCandidates = orderCoordinates(candidates, schema);
  const coordinate = orderedCandidates.find((candidate) =>
    records.some((record) => numericScalar(valueFor(record, candidate)) !== undefined),
  );
  const points = records.flatMap((record) => {
    const y = numericScalar(valueFor(record, observable));
    const x = coordinate ? numericScalar(valueFor(record, coordinate)) : record.pointIndex;
    return x === undefined || y === undefined ? [] : [{ x, y }];
  });
  if (points.length === 0) return [];
  const complex =
    observable.dtype === "complex128" ||
    records.some((record) => isComplexValue(valueFor(record, observable)));
  const pointCloud = pointDomainLayout(schema) === "point_cloud";
  return [
    {
      id: `scalar:${observable.id}:${coordinate?.id ?? "point"}`,
      kind: pointCloud || !strictlyMonotonic(points) ? "scatter" : "line",
      title: complex ? `${observable.label} magnitude` : observable.label,
      xLabel: coordinate ? valueLabel(coordinate) : "Point index",
      yLabel: valueLabel(observable, complex),
      note: complex ? "Complex values are shown as magnitude." : undefined,
      series: [{ id: observable.id, label: observable.label, points }],
    },
  ];
}

function traceChart(
  records: MeasurementRecordView[],
  variables: VariableDescriptor[],
  observable: VariableDescriptor,
): MeasurementChartPlan[] {
  const coordinate = traceCoordinate(variables, observable);
  const complex =
    observable.dtype === "complex128" ||
    records.some((record) => isComplexValue(valueFor(record, observable)));
  const series = records
    .flatMap((record, index) => {
      const y = numericArray(valueFor(record, observable));
      if (!y || y.length === 0) return [];
      const candidateX = coordinate ? numericArray(valueFor(record, coordinate)) : undefined;
      const x = candidateX?.length === y.length ? candidateX : y.map((_value, item) => item);
      return [
        {
          id: `${record.pointIndex}:${index}`,
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

function variableDescriptors(
  records: MeasurementRecordView[],
  schema?: MeasurementDatasetSchema,
): VariableDescriptor[] {
  if (schema?.variables && schema.variables.length > 0) {
    return schema.variables.map(schemaVariable);
  }
  return inferVariables(records);
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

function inferVariables(records: MeasurementRecordView[]): VariableDescriptor[] {
  const variables: VariableDescriptor[] = [];
  const seen = new Set<string>();
  for (const role of ["coordinate", "observable"] as const) {
    for (const record of records) {
      const values = role === "coordinate" ? record.coordinates : record.observables;
      for (const [id, raw] of Object.entries(values)) {
        const key = `${role}:${id}`;
        if (seen.has(key)) continue;
        seen.add(key);
        const value = parseValue(raw);
        const rank = value?.kind === "array" ? value.shape.length : 0;
        variables.push({
          id,
          role,
          dtype: value?.dtype ?? inferDType(value),
          unit: value?.unit,
          dims: [
            "point",
            ...Array.from({ length: rank }, (_item, index) =>
              rank === 1 ? "sample" : `sample_${index}`,
            ),
          ],
          label: dimensionLabel(id),
        });
      }
    }
  }
  return variables;
}

function orderObservables(
  variables: VariableDescriptor[],
  schema?: MeasurementDatasetSchema,
): VariableDescriptor[] {
  const observables = variables.filter((variable) => variable.role === "observable");
  const primary = new Map((schema?.primary_observables ?? []).map((id, index) => [id, index]));
  return [...observables].sort(
    (left, right) =>
      (primary.get(left.id) ?? Number.MAX_SAFE_INTEGER) -
      (primary.get(right.id) ?? Number.MAX_SAFE_INTEGER),
  );
}

function orderCoordinates(
  variables: VariableDescriptor[],
  schema?: MeasurementDatasetSchema,
): VariableDescriptor[] {
  const primary = new Map((schema?.primary_coordinates ?? []).map((id, index) => [id, index]));
  return [...variables].sort(
    (left, right) =>
      (primary.get(left.id) ?? Number.MAX_SAFE_INTEGER) -
      (primary.get(right.id) ?? Number.MAX_SAFE_INTEGER),
  );
}

function parseRecords(items: Array<Record<string, unknown>>): MeasurementRecordView[] {
  return items.map((item, index) => ({
    pointIndex: typeof item.point_index === "number" ? item.point_index : index,
    coordinates: objectMap(item.coordinates),
    observables: objectMap(item.observables),
  }));
}

function objectMap(value: unknown): Record<string, unknown> {
  return isObject(value) ? value : {};
}

function valueFor(record: MeasurementRecordView, variable: VariableDescriptor): unknown {
  return variable.role === "coordinate"
    ? record.coordinates[variable.id]
    : record.observables[variable.id];
}

function parseValue(raw: unknown): ParsedValue | undefined {
  if (Array.isArray(raw)) {
    return { kind: "array", shape: arrayShape(raw), values: raw };
  }
  if (!isObject(raw)) {
    return raw === undefined ? undefined : { kind: "scalar", value: raw };
  }
  if (raw.kind === "scalar") {
    return {
      kind: "scalar",
      dtype: text(raw.dtype),
      unit: text(raw.unit),
      value: raw.value,
    };
  }
  if (raw.kind === "array") {
    return {
      kind: "array",
      dtype: text(raw.dtype),
      unit: text(raw.unit),
      shape: numberArray(raw.shape) ?? arrayShape(raw.values),
      values: raw.values,
    };
  }
  if (raw.kind === "unavailable") {
    return {
      kind: "unavailable",
      dtype: text(raw.dtype),
      unit: text(raw.unit),
      shape: numberArray(raw.shape) ?? [],
      reason: text(raw.reason) ?? "unavailable",
    };
  }
  if (complexComponents(raw) !== undefined) {
    return { kind: "scalar", dtype: "complex128", value: raw };
  }
  return undefined;
}

function numericScalar(raw: unknown): number | undefined {
  const parsed = parseValue(raw);
  if (parsed?.kind !== "scalar") return undefined;
  if (typeof parsed.value === "number" && Number.isFinite(parsed.value)) return parsed.value;
  const complex = complexComponents(parsed.value);
  return complex ? Math.hypot(complex.real, complex.imag) : undefined;
}

function numericArray(raw: unknown): number[] | undefined {
  const parsed = parseValue(raw);
  if (parsed?.kind !== "array" || parsed.shape.length !== 1 || !Array.isArray(parsed.values)) {
    return undefined;
  }
  const values = parsed.values.map(numericLeaf);
  return values.every((value) => value !== undefined) ? (values as number[]) : undefined;
}

function numericLeaf(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const complex = complexComponents(value);
  return complex ? Math.hypot(complex.real, complex.imag) : undefined;
}

function complexComponents(value: unknown): { real: number; imag: number } | undefined {
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

function isComplexValue(raw: unknown): boolean {
  const parsed = parseValue(raw);
  if (!parsed) return false;
  if (parsed.dtype === "complex128") return true;
  if (parsed.kind === "scalar") return complexComponents(parsed.value) !== undefined;
  return (
    parsed.kind === "array" &&
    Array.isArray(parsed.values) &&
    parsed.values.some((value) => complexComponents(value) !== undefined)
  );
}

function traceSeriesLabel(record: MeasurementRecordView, variables: VariableDescriptor[]): string {
  const coordinates = variables
    .filter((variable) => variable.role === "coordinate" && variable.dims.length === 1)
    .flatMap((variable) => {
      const parsed = parseValue(valueFor(record, variable));
      return parsed?.kind === "scalar"
        ? [
            `${variable.label} ${formatScalar(parsed.value)}${unitSuffix(parsed.unit ?? variable.unit)}`,
          ]
        : [];
    });
  return coordinates.length > 0 ? coordinates.join(" · ") : `Point ${record.pointIndex}`;
}

function formatMeasurementValue(raw: unknown, fallbackUnit?: string): string {
  const value = parseValue(raw);
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

function unitSuffix(unit?: string): string {
  return unit ? ` ${unit}` : "";
}

function dimensionLabel(id: string): string {
  return id.replaceAll(/[-_/]+/g, " ").replaceAll(/\b\w/g, (letter) => letter.toLocaleUpperCase());
}

function inferDType(value?: ParsedValue): string {
  if (!value) return "unknown";
  if (value.dtype) return value.dtype;
  const sample = value.kind === "scalar" ? value.value : undefined;
  if (complexComponents(sample)) return "complex128";
  if (typeof sample === "number") return "float64";
  return typeof sample;
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

function pointDomainLayout(schema?: MeasurementDatasetSchema): string | undefined {
  const metadata = schema?.metadata;
  if (!isObject(metadata)) return undefined;
  const direct = text(metadata.point_domain_layout) ?? text(metadata.domain_layout);
  if (direct) return direct;
  const domain = metadata.point_domain;
  return isObject(domain) ? (text(domain.layout) ?? text(domain.kind)) : undefined;
}

function arrayShape(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  if (value.length === 0) return [0];
  const nested = arrayShape(value[0]);
  return [value.length, ...nested];
}

function numberArray(value: unknown): number[] | undefined {
  if (!Array.isArray(value) || !value.every((item) => typeof item === "number")) {
    return undefined;
  }
  return value;
}

function text(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

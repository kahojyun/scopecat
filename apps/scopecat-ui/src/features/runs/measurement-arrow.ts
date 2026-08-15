import { DataType, tableFromIPC, type Field, type Table } from "apache-arrow";
import type { MeasurementRecord, MeasurementValue } from "../../api-contract";

type MeasurementArray = Extract<MeasurementValue, { kind: "array" }>;
type MeasurementSegmentedArray = Extract<MeasurementValue, { kind: "segmented_array" }>;
type MeasurementUnavailable = Extract<MeasurementValue, { kind: "unavailable" }>;
type MeasurementDType = MeasurementValue["dtype"];

const textDecoder = new TextDecoder();

export function decodeMeasurementArrowRecord(content: ArrayBuffer): MeasurementRecord {
  const table = tableFromIPC(new Uint8Array(content));
  if (table.numRows !== 1) throw new Error("live measurement Arrow must contain one row");

  const coordinates: Record<string, MeasurementValue> = {};
  const observables: Record<string, MeasurementValue> = {};

  for (const field of table.schema.fields) {
    if (!field.name.startsWith("value:")) continue;
    const variableId = field.name.slice("value:".length);
    const role = requiredMetadata(field, "scopecat.variable_role");
    const dtype = requiredMetadata(field, "scopecat.variable_dtype") as MeasurementDType;
    const declaredKind = requiredMetadata(field, "scopecat.variable_kind");
    const unit = field.metadata.get("scopecat.variable_unit") ?? null;
    const metadata = decodeJsonColumn(table, `metadata:${variableId}`);
    const reason = columnValue(table, `unavailable_reason:${variableId}`);
    const shapeSidecar = decodeOptionalJsonColumn(table, `value_shape:${variableId}`);
    const availabilitySidecar = decodeJsonColumn(table, `availability:${variableId}`);
    const rawValue = plainValue(columnValue(table, field.name));
    let value: MeasurementValue;

    if (typeof reason === "string") {
      value = decodeUnavailable(reason, dtype, unit, shapeSidecar, metadata);
    } else if (declaredKind === "scalar") {
      value = {
        kind: "scalar",
        dtype,
        unit,
        value: rawValue as Extract<MeasurementValue, { kind: "scalar" }>["value"],
        metadata,
      };
    } else if (isSegmentShapeSidecar(shapeSidecar)) {
      value = decodeSegmentedArray(
        rawValue,
        dtype,
        unit,
        shapeSidecar.segments,
        availabilitySidecar,
        metadata,
      );
    } else {
      value = decodeArray(
        rawValue,
        dtype,
        unit,
        arrayShape(shapeSidecar, field),
        availabilitySidecar,
        metadata,
      );
    }

    (role === "coordinate" ? coordinates : observables)[variableId] = value;
  }

  return {
    run_id: requiredSchemaMetadata(table, "scopecat.run_id"),
    logical_point_id: columnValue(table, "__scopecat.logical_point_id") as string | null,
    point_index: numericValue(columnValue(table, "__scopecat.point_index")),
    coordinates,
    observables,
    acquisition_evidence: decodeJsonColumn(table, "__scopecat.acquisition_evidence"),
    metadata: decodeJsonColumn(table, "__scopecat.record_metadata"),
  };
}

function decodeUnavailable(
  reason: string,
  dtype: MeasurementDType,
  unit: string | null,
  shapeSidecar: Record<string, unknown> | null,
  metadata: Record<string, unknown>,
): MeasurementUnavailable {
  const shape = shapeSidecar?.shape;
  if (!isShape(shape)) throw new Error("live measurement Arrow unavailable shape is invalid");
  return {
    kind: "unavailable",
    reason: reason as MeasurementUnavailable["reason"],
    dtype,
    unit,
    shape,
    metadata,
  };
}

function decodeArray(
  rawValue: unknown,
  dtype: MeasurementDType,
  unit: string | null,
  shape: number[],
  availabilitySidecar: Record<string, unknown>,
  metadata: Record<string, unknown>,
): MeasurementArray {
  const unavailable = unavailableGroups(availabilitySidecar);
  const decoded = decodeNullableArray(rawValue, dtype);
  const value: MeasurementArray = {
    kind: "array",
    dtype,
    unit,
    shape,
    values: decoded.values as MeasurementArray["values"],
    metadata,
  };
  if (unavailable.length > 0) {
    value.availability = {
      valid: decoded.valid as NonNullable<MeasurementArray["availability"]>["valid"],
      unavailable,
    };
  }
  return value;
}

function decodeSegmentedArray(
  rawValue: unknown,
  dtype: MeasurementDType,
  unit: string | null,
  shapeSpecs: unknown[],
  availabilitySidecar: Record<string, unknown>,
  metadata: Record<string, unknown>,
): MeasurementSegmentedArray {
  if (!Array.isArray(rawValue)) {
    throw new Error("live measurement Arrow segmented value is invalid");
  }
  const diagnostics = availabilitySidecar.segments;
  if (!Array.isArray(diagnostics) || diagnostics.length !== shapeSpecs.length) {
    throw new Error("live measurement Arrow segmented diagnostics are invalid");
  }
  if (rawValue.length !== shapeSpecs.length) {
    throw new Error("live measurement Arrow segmented cardinality is invalid");
  }

  const segments = diagnostics.map((rawDiagnostic, index) => {
    if (!isJsonObject(rawDiagnostic)) {
      throw new Error("live measurement Arrow segmented diagnostics are invalid");
    }
    const segmentMetadata = rawDiagnostic.metadata;
    if (!isJsonObject(segmentMetadata)) {
      throw new Error("live measurement Arrow segmented metadata is invalid");
    }
    const shapeSpec = segmentShape(shapeSpecs[index]);
    if (rawDiagnostic.kind === "unavailable") {
      if (typeof rawDiagnostic.reason !== "string" || shapeSpec === null) {
        throw new Error("live measurement Arrow unavailable segment is invalid");
      }
      return {
        kind: "unavailable" as const,
        reason: rawDiagnostic.reason as MeasurementUnavailable["reason"],
        dtype,
        unit,
        shape: shapeSpec,
        metadata: segmentMetadata,
      };
    }
    if (rawDiagnostic.kind !== "array" || rawValue[index] === null) {
      throw new Error("live measurement Arrow available segment is invalid");
    }
    if (shapeSpec?.some((extent) => extent === null)) {
      throw new Error("live measurement Arrow available segment shape is not concrete");
    }
    return decodeArray(
      rawValue[index],
      dtype,
      unit,
      (shapeSpec as number[] | null) ?? nestedShape(rawValue[index]),
      rawDiagnostic,
      segmentMetadata,
    );
  });

  return { kind: "segmented_array", dtype, unit, segments, metadata };
}

function decodeNullableArray(
  value: unknown,
  dtype: MeasurementDType,
): { values: unknown; valid: unknown } {
  if (!Array.isArray(value)) {
    return {
      values: value === null ? unavailableFill(dtype) : value,
      valid: value !== null,
    };
  }
  const children = value.map((item) => decodeNullableArray(item, dtype));
  return {
    values: children.map((child) => child.values),
    valid: children.map((child) => child.valid),
  };
}

function unavailableFill(dtype: MeasurementDType): unknown {
  if (dtype === "string") return "";
  if (dtype === "bool") return false;
  if (dtype === "complex128") return { real: 0, imag: 0 };
  return 0;
}

function arrayShape(shapeSidecar: Record<string, unknown> | null, field: Field): number[] {
  if (shapeSidecar !== null) {
    if (!isConcreteShape(shapeSidecar.shape)) {
      throw new Error("live measurement Arrow array shape is invalid");
    }
    return shapeSidecar.shape;
  }
  return shapeFromType(field.type);
}

function segmentShape(value: unknown): (number | null)[] | null {
  if (value === null) return null;
  if (!isJsonObject(value) || !isShape(value.shape)) {
    throw new Error("live measurement Arrow segmented shape is invalid");
  }
  return value.shape;
}

function nestedShape(value: unknown): number[] {
  if (!Array.isArray(value)) {
    throw new Error("live measurement Arrow array value is not nested");
  }
  if (value.length === 0) return [0];
  const childShapes = value.map((item) => (Array.isArray(item) ? nestedShape(item) : []));
  const first = childShapes[0]!;
  const rest = childShapes.slice(1);
  if (rest.some((shape) => shape.length !== first.length || shape.some((x, i) => x !== first[i]))) {
    throw new Error("live measurement Arrow array value is not rectangular");
  }
  return [value.length, ...first];
}

function unavailableGroups(
  value: Record<string, unknown>,
): NonNullable<MeasurementArray["availability"]>["unavailable"] {
  const groups = value.unavailable ?? [];
  if (!Array.isArray(groups)) {
    throw new Error("live measurement Arrow array availability is invalid");
  }
  return groups as NonNullable<MeasurementArray["availability"]>["unavailable"];
}

function columnValue(table: Table, name: string): unknown {
  const column = table.getChild(name);
  if (column === null) throw new Error(`live measurement Arrow is missing ${name}`);
  return column.get(0);
}

function decodeJsonColumn(table: Table, name: string): Record<string, unknown> {
  const value = columnValue(table, name);
  if (!(value instanceof Uint8Array)) throw new Error(`${name} is not binary JSON metadata`);
  const decoded = JSON.parse(textDecoder.decode(value)) as unknown;
  if (!isJsonObject(decoded)) throw new Error(`${name} JSON metadata is not an object`);
  return decoded;
}

function decodeOptionalJsonColumn(table: Table, name: string): Record<string, unknown> | null {
  const value = columnValue(table, name);
  if (value === null) return null;
  if (!(value instanceof Uint8Array)) throw new Error(`${name} is not binary JSON metadata`);
  const decoded = JSON.parse(textDecoder.decode(value)) as unknown;
  if (!isJsonObject(decoded)) throw new Error(`${name} JSON metadata is not an object`);
  return decoded;
}

function plainValue(value: unknown): unknown {
  if (typeof value === "bigint") return Number(value);
  if (value === null || typeof value !== "object") return value;
  if (value instanceof Uint8Array) return value;
  if ("toJSON" in value && typeof value.toJSON === "function") {
    return plainValue(value.toJSON());
  }
  if (Symbol.iterator in value) {
    return Array.from(value as Iterable<unknown>, plainValue);
  }
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, plainValue(item)]));
}

function shapeFromType(type: DataType): number[] {
  const shape: number[] = [];
  let current = type;
  while (DataType.isFixedSizeList(current)) {
    shape.push(current.listSize);
    current = current.valueType;
  }
  return shape;
}

function isSegmentShapeSidecar(
  value: Record<string, unknown> | null,
): value is { segments: unknown[] } {
  return value !== null && Array.isArray(value.segments);
}

function isShape(value: unknown): value is (number | null)[] {
  return (
    Array.isArray(value) &&
    value.every((extent) => extent === null || (Number.isInteger(extent) && extent >= 0))
  );
}

function isConcreteShape(value: unknown): value is number[] {
  return Array.isArray(value) && value.every((extent) => Number.isInteger(extent) && extent >= 0);
}

function isJsonObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function requiredMetadata(field: Field, name: string): string {
  const value = field.metadata.get(name);
  if (value === undefined) throw new Error(`live measurement Arrow field is missing ${name}`);
  return value;
}

function requiredSchemaMetadata(table: Table, name: string): string {
  const value = table.schema.metadata.get(name);
  if (value === undefined) throw new Error(`live measurement Arrow schema is missing ${name}`);
  return value;
}

function numericValue(value: unknown): number {
  if (typeof value === "number") return value;
  if (typeof value === "bigint") return Number(value);
  throw new Error("live measurement Arrow point index is not numeric");
}

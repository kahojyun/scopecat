import { DataType, tableFromIPC, type Field, type Table } from "apache-arrow";
import type { MeasurementRecord, MeasurementValue } from "../../api-contract";

const textDecoder = new TextDecoder();

export function decodeMeasurementArrowRecord(content: ArrayBuffer): MeasurementRecord {
  const table = tableFromIPC(new Uint8Array(content));
  if (table.numRows !== 1) throw new Error("live measurement Arrow must contain one row");

  const coordinates: Record<string, MeasurementValue> = {};
  const observables: Record<string, MeasurementValue> = {};
  const acquisitionEvidence: Record<string, never> = {};

  for (const field of table.schema.fields) {
    if (!field.name.startsWith("value:")) continue;
    const variableId = field.name.slice("value:".length);
    const role = requiredMetadata(field, "scopecat.variable_role");
    const dtype = requiredMetadata(field, "scopecat.variable_dtype") as MeasurementValue["dtype"];
    const kind = requiredMetadata(field, "scopecat.variable_kind");
    const unit = field.metadata.get("scopecat.variable_unit") ?? null;
    const metadata = decodeJsonColumn(table, `metadata:${variableId}`);
    const reason = columnValue(table, `unavailable_reason:${variableId}`);
    const encodedShape = plainValue(columnValue(table, `value_shape:${variableId}`));
    const rawValue = columnValue(table, field.name);
    let value: MeasurementValue;

    if (typeof reason === "string") {
      value = {
        kind: "unavailable",
        reason: reason as "missing" | "invalid" | "overload",
        dtype,
        unit,
        shape: (encodedShape as (number | null)[]) ?? shapeFromType(field.type),
        metadata,
      };
    } else if (kind === "scalar") {
      value = {
        kind: "scalar",
        dtype,
        unit,
        value: plainValue(rawValue) as Extract<MeasurementValue, { kind: "scalar" }>["value"],
        metadata,
      };
    } else {
      value = {
        kind: "array",
        dtype,
        unit,
        shape: (encodedShape as number[] | null) ?? shapeFromType(field.type),
        values: plainValue(rawValue) as Extract<MeasurementValue, { kind: "array" }>["values"],
        metadata,
      };
    }

    (role === "coordinate" ? coordinates : observables)[variableId] = value;
    const evidence = plainValue(columnValue(table, `evidence:${variableId}`));
    if (evidence !== null) {
      acquisitionEvidence[variableId] = evidence as never;
    }
  }

  return {
    run_id: requiredSchemaMetadata(table, "scopecat.run_id"),
    logical_point_id: columnValue(table, "__scopecat.logical_point_id") as string | null,
    point_index: numericValue(columnValue(table, "__scopecat.point_index")),
    coordinates,
    observables,
    acquisition_evidence: acquisitionEvidence,
    metadata: decodeJsonColumn(table, "__scopecat.record_metadata"),
  };
}

function columnValue(table: Table, name: string): unknown {
  const column = table.getChild(name);
  if (column === null) throw new Error(`live measurement Arrow is missing ${name}`);
  return column.get(0);
}

function decodeJsonColumn(table: Table, name: string): Record<string, unknown> {
  const value = columnValue(table, name);
  if (!(value instanceof Uint8Array)) throw new Error(`${name} is not binary JSON metadata`);
  return JSON.parse(textDecoder.decode(value)) as Record<string, unknown>;
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

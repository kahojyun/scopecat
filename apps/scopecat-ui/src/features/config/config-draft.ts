import type {
  ConfigProfileSnapshot,
  ParameterAtom,
  ParameterEntity,
  ParameterScalarType,
  ParameterUpdate,
  StoredParameterValue,
  TableParameterType,
  TableParameterValue,
} from "../../api-contract";
import { parameterAtomIdentity } from "./config-diff";

export function deriveConfigDraftUpdates(
  config: ConfigProfileSnapshot,
  editedValues: Record<string, StoredParameterValue>,
): ParameterUpdate[] {
  const values = config.parameter_snapshot.values ?? [];
  const definitions = config.system.parameter_catalog.definitions ?? [];
  const baseValues = new Map(values.map((value) => [value.id, value]));
  const definitionsById = new Map(definitions.map((definition) => [definition.id, definition]));
  const updates: ParameterUpdate[] = [];

  for (const definition of definitions) {
    const edited = editedValues[definition.id];
    const base = baseValues.get(definition.id);
    if (!edited || !base || storedValuesEqual(base, edited)) continue;
    if (
      definition.value_type.shape === "table" &&
      base.shape === "table" &&
      edited.shape === "table" &&
      (definition.value_type.primary_key?.length ?? 0) > 0
    ) {
      updates.push(...deriveKeyedTableUpdates(definition.value_type, base, edited));
      continue;
    }
    updates.push({ kind: "replace_parameter", value: edited });
  }

  for (const [parameterId, edited] of Object.entries(editedValues)) {
    if (
      definitionsById.has(parameterId) ||
      storedValuesEqual(baseValues.get(parameterId), edited)
    ) {
      continue;
    }
    updates.push({ kind: "replace_parameter", value: edited });
  }
  return updates;
}

export function cloneStoredParameterValue(value: StoredParameterValue): StoredParameterValue {
  return structuredClone(value);
}

export function defaultParameterAtom(
  type: ParameterScalarType,
  entities: ParameterEntity[],
): ParameterAtom {
  if (type.nullable) return null;
  switch (type.type) {
    case "bool":
      return false;
    case "int":
      return Math.ceil(type.minimum ?? 0);
    case "float":
      return type.minimum ?? 0;
    case "string":
      return type.choices?.[0] ?? "";
    case "quantity":
      return {
        value: type.minimum ?? 0,
        unit: type.unit ?? "",
      };
    case "entity": {
      const selected = entities.find(
        (entity) => !type.entity_kind || entity.kind === type.entity_kind,
      );
      return (
        selected ?? {
          id: "",
          ...(type.entity_kind ? { kind: type.entity_kind } : {}),
          metadata: {},
        }
      );
    }
  }
}

export function defaultTableRow(
  type: TableParameterType,
  entities: ParameterEntity[],
): Record<string, ParameterAtom> {
  return Object.fromEntries(
    type.columns.map((column) => [
      column.id,
      (column.required ?? true) || !column.value_type.nullable
        ? defaultParameterAtom(column.value_type, entities)
        : null,
    ]),
  );
}

function deriveKeyedTableUpdates(
  type: TableParameterType,
  base: TableParameterValue,
  edited: TableParameterValue,
): ParameterUpdate[] {
  const primaryKey = type.primary_key ?? [];
  const baseRows = new Map(
    (base.rows ?? []).map((row) => [tableRowIdentity(row, primaryKey), row]),
  );
  const editedRows = new Map<string, Array<Record<string, ParameterAtom>>>();
  for (const row of edited.rows ?? []) {
    const identity = tableRowIdentity(row, primaryKey);
    editedRows.set(identity, [...(editedRows.get(identity) ?? []), row]);
  }
  if ([...editedRows.values()].some((rows) => rows.length > 1)) {
    return [{ kind: "replace_parameter", value: edited }];
  }
  const updates: ParameterUpdate[] = [];

  for (const [identity, row] of baseRows) {
    if (!editedRows.has(identity)) {
      updates.push({
        kind: "delete_parameter_rows",
        parameter_id: base.id,
        key: pickColumns(row, primaryKey),
      });
    }
  }

  for (const [identity, rows] of editedRows) {
    const before = baseRows.get(identity);
    if (!before) continue;
    const row = rows[0]!;
    const values = Object.fromEntries(
      type.columns
        .filter((column) => !primaryKey.includes(column.id))
        .filter((column) => !atomsEqual(before[column.id], row[column.id]))
        .map((column) => [column.id, row[column.id] ?? null]),
    );
    if (Object.keys(values).length > 0) {
      updates.push({
        kind: "update_parameter_rows",
        parameter_id: base.id,
        key: pickColumns(row, primaryKey),
        values,
      });
    }
  }

  const insertedRows = [...editedRows].flatMap(([identity, rows]) =>
    baseRows.has(identity) ? rows.slice(1) : rows,
  );
  if (insertedRows.length > 0) {
    updates.push({
      kind: "insert_parameter_rows",
      parameter_id: base.id,
      rows: insertedRows as [Record<string, ParameterAtom>, ...Record<string, ParameterAtom>[]],
    });
  }
  return updates;
}

function pickColumns(
  row: Record<string, ParameterAtom>,
  columns: string[],
): Record<string, ParameterAtom> {
  return Object.fromEntries(columns.map((column) => [column, row[column] ?? null]));
}

function tableRowIdentity(row: Record<string, ParameterAtom>, primaryKey: string[]): string {
  return JSON.stringify(primaryKey.map((column) => parameterAtomIdentity(row[column] ?? null)));
}

function atomsEqual(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function storedValuesEqual(
  left: StoredParameterValue | undefined,
  right: StoredParameterValue,
): boolean {
  if (!left || left.shape !== right.shape) return false;
  if (left.shape === "scalar" && right.shape === "scalar") {
    return atomsEqual(left.value, right.value);
  }
  if (left.shape === "series" && right.shape === "series") {
    return atomsEqual(left.items ?? [], right.items ?? []);
  }
  if (left.shape === "table" && right.shape === "table") {
    return atomsEqual(left.rows ?? [], right.rows ?? []);
  }
  return false;
}

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import cast

from scopecat.models.parameter import (
    ParameterCatalog,
    ParameterChangeSet,
    ParameterDefinition,
    ParameterPatch,
    ParameterPatchValue,
    ParameterState,
    ParameterTable,
    ParameterTableDefinition,
    ParameterValueSet,
    Quantity,
)
from scopecat.parameter_validation import (
    ParameterTableCellValidationError,
    coerce_parameter_table,
    coerce_parameter_table_cell,
    parameter_table_key_part,
)
from scopecat.units import compatible_units, to_base_value


def apply_parameter_patches(
    *,
    catalog: ParameterCatalog,
    parameter_state: ParameterState,
    patches: Sequence[ParameterPatch],
    state_id: str | None = None,
    allow_table_row_changes: bool = False,
) -> ParameterState:
    """Apply concrete patches to accepted parameter state and return a candidate."""

    parameter_state = _normalize_parameter_state_tables(catalog, parameter_state)
    scalar_by_id = {
        value.id: value.model_copy(deep=True)
        for value in parameter_state.scalar_value_set().values
    }
    table_by_id = {
        table.id: table.model_copy(deep=True) for table in parameter_state.tables
    }
    for patch in patches:
        if patch.kind == "set_scalar":
            parameter_id = _required(patch.parameter_id)
            value = _quantity_value(patch.value, path=f"{parameter_id}.value")
            definition = catalog.scalar(parameter_id)
            if definition is None:
                msg = f"unknown scalar parameter {parameter_id!r}"
                raise ValueError(msg)
            current = scalar_by_id.get(parameter_id)
            if current is None:
                msg = f"parameter state is missing scalar {parameter_id!r}"
                raise ValueError(msg)
            if patch.expected_value is not None:
                _assert_equal(
                    current.quantity,
                    _quantity_value(
                        patch.expected_value,
                        path=f"{parameter_id}.expected_value",
                    ),
                    path=f"{parameter_id}.expected_value",
                )
            _validate_quantity_unit(value, definition.unit, path=parameter_id)
            _validate_scalar_safety(definition, value)
            scalar_by_id[parameter_id] = current.model_copy(
                update={"quantity": value},
                deep=True,
            )
        elif patch.kind == "update_rows":
            table_id = _required(patch.table_id)
            definition = _table_definition(catalog, table_id)
            table = _table_value(table_by_id, table_id)
            key = dict(_required(patch.key))
            values = dict(_required(patch.values))
            _validate_key(definition, key)
            _validate_patch_columns(definition, values, allow_primary_key=False)
            rows = [dict(row) for row in table.rows]
            row = _find_one_row(rows, definition, key)
            if patch.expected_values is not None:
                for column_id, expected in patch.expected_values.items():
                    _assert_equal(
                        row.get(column_id),
                        _validate_cell_value(definition, column_id, expected),
                        path=f"{table_id}.{column_id}.expected_value",
                    )
            for column_id, value in values.items():
                row[column_id] = value
            table_by_id[table_id] = table.model_copy(update={"rows": rows}, deep=True)
        elif patch.kind == "insert_rows":
            _validate_table_row_change_allowed(
                allow_table_row_changes,
                patch_kind=patch.kind,
            )
            table_id = _required(patch.table_id)
            definition = _table_definition(catalog, table_id)
            table = _table_value(table_by_id, table_id)
            rows = [dict(row) for row in table.rows]
            for raw_row in _required(patch.rows):
                row = dict(raw_row)
                _validate_row(definition, row)
                key = _row_key(definition, row)
                if _matching_rows(rows, key):
                    msg = f"insert_rows key already exists in {table_id!r}: {key!r}"
                    raise ValueError(msg)
                rows.append(dict(row))
            table_by_id[table_id] = table.model_copy(update={"rows": rows}, deep=True)
        elif patch.kind == "delete_rows":
            _validate_table_row_change_allowed(
                allow_table_row_changes,
                patch_kind=patch.kind,
            )
            table_id = _required(patch.table_id)
            definition = _table_definition(catalog, table_id)
            table = _table_value(table_by_id, table_id)
            key = dict(_required(patch.key))
            _validate_key(definition, key)
            rows = [dict(row) for row in table.rows]
            row = _find_one_row(rows, definition, key)
            if patch.expected_values is not None:
                for column_id, expected in patch.expected_values.items():
                    _assert_equal(
                        row.get(column_id),
                        _validate_cell_value(definition, column_id, expected),
                        path=f"{table_id}.{column_id}.expected_value",
                    )
            rows.remove(row)
            table_by_id[table_id] = table.model_copy(update={"rows": rows}, deep=True)
        else:
            msg = f"unsupported parameter patch kind: {patch.kind}"
            raise ValueError(msg)

    parameter_values = ParameterValueSet.model_validate(
        parameter_state.scalar_value_set().model_dump(mode="python")
        | {"values": list(scalar_by_id.values())}
    )
    return ParameterState.model_validate(
        parameter_state.model_dump(mode="python")
        | {
            "id": state_id or parameter_state.id,
            "scalar_values": parameter_values,
            "tables": list(table_by_id.values()),
        }
    )


def diff_parameter_states(
    *,
    id: str,  # noqa: A002
    source_run_id: str,
    reason: str,
    catalog: ParameterCatalog,
    before: ParameterState,
    after: ParameterState,
    confidence: float | None = None,
) -> ParameterChangeSet:
    """Create a concrete change set from accepted and candidate states."""

    before = _normalize_parameter_state_tables(catalog, before)
    after = _normalize_parameter_state_tables(catalog, after)
    patches: list[ParameterPatch] = []
    before_scalars = {
        value.id: value.quantity for value in before.scalar_value_set().values
    }
    after_scalars = {
        value.id: value.quantity for value in after.scalar_value_set().values
    }
    for parameter_id in sorted(set(before_scalars) | set(after_scalars)):
        before_value = before_scalars.get(parameter_id)
        after_value = after_scalars.get(parameter_id)
        if before_value is None or after_value is None:
            msg = "scalar additions and deletions are not supported by ParameterPatch"
            raise ValueError(msg)
        if not _cell_equal(before_value, after_value):
            patches.append(
                ParameterPatch(
                    kind="set_scalar",
                    parameter_id=parameter_id,
                    expected_value=before_value,
                    value=after_value,
                )
            )

    before_tables = {table.id: table.rows for table in before.tables}
    after_tables = {table.id: table.rows for table in after.tables}
    for table_id in sorted(set(before_tables) | set(after_tables)):
        definition = _table_definition(catalog, table_id)
        before_rows = _rows_by_key(definition, before_tables.get(table_id, []))
        after_rows = _rows_by_key(definition, after_tables.get(table_id, []))
        for key_tuple in sorted(before_rows.keys() - after_rows.keys(), key=repr):
            row = before_rows[key_tuple]
            patches.append(
                ParameterPatch(
                    kind="delete_rows",
                    table_id=table_id,
                    key=_row_key(definition, row),
                    expected_values=dict(row),
                )
            )
        for key_tuple in sorted(after_rows.keys() - before_rows.keys(), key=repr):
            patches.append(
                ParameterPatch(
                    kind="insert_rows",
                    table_id=table_id,
                    rows=[dict(after_rows[key_tuple])],
                )
            )
        for key_tuple in sorted(before_rows.keys() & after_rows.keys(), key=repr):
            before_row = before_rows[key_tuple]
            after_row = after_rows[key_tuple]
            changed = {
                column_id: after_row[column_id]
                for column_id in after_row
                if column_id not in definition.primary_key
                and not _cell_equal(before_row.get(column_id), after_row[column_id])
            }
            if changed:
                patches.append(
                    ParameterPatch(
                        kind="update_rows",
                        table_id=table_id,
                        key=_row_key(definition, before_row),
                        values=changed,
                        expected_values={
                            column_id: before_row.get(column_id)
                            for column_id in changed
                        },
                    )
                )
    if not patches:
        msg = "parameter states have no differences"
        raise ValueError(msg)
    return ParameterChangeSet(
        id=id,
        source_run_id=source_run_id,
        reason=reason,
        patches=patches,
        confidence=confidence,
    )


def _table_definition(
    catalog: ParameterCatalog,
    table_id: str,
) -> ParameterTableDefinition:
    definition = catalog.table(table_id)
    if definition is None:
        msg = f"unknown parameter table {table_id!r}"
        raise ValueError(msg)
    return definition


def _table_value(
    table_by_id: dict[str, ParameterTable],
    table_id: str,
) -> ParameterTable:
    try:
        return table_by_id[table_id]
    except KeyError as exc:
        msg = f"parameter state is missing table {table_id!r}"
        raise ValueError(msg) from exc


def _validate_table_row_change_allowed(
    allow_table_row_changes: bool,
    *,
    patch_kind: str,
) -> None:
    if not allow_table_row_changes:
        msg = f"{patch_kind} patches require explicit table row change permission"
        raise ValueError(msg)


def _validate_key(
    definition: ParameterTableDefinition,
    key: dict[str, ParameterPatchValue],
) -> None:
    expected = set(definition.primary_key)
    actual = set(key)
    if actual != expected:
        msg = (
            f"table {definition.id!r} key must contain "
            f"{sorted(expected)!r}, got {sorted(actual)!r}"
        )
        raise ValueError(msg)
    for column_id, value in key.items():
        key[column_id] = _validate_cell_value(definition, column_id, value)


def _validate_patch_columns(
    definition: ParameterTableDefinition,
    values: dict[str, ParameterPatchValue],
    *,
    allow_primary_key: bool,
) -> None:
    if not values:
        msg = f"table {definition.id!r} patch must contain at least one value"
        raise ValueError(msg)
    primary_key = set(definition.primary_key)
    for column_id, value in values.items():
        if not allow_primary_key and column_id in primary_key:
            msg = f"table {definition.id!r} cannot update primary key {column_id!r}"
            raise ValueError(msg)
        values[column_id] = _validate_cell_value(definition, column_id, value)


def _validate_row(
    definition: ParameterTableDefinition,
    row: dict[str, ParameterPatchValue],
) -> None:
    column_ids = {column.id for column in definition.columns}
    extra = sorted(set(row) - column_ids)
    if extra:
        msg = f"table {definition.id!r} row has unknown columns: {extra!r}"
        raise ValueError(msg)
    for column in definition.columns:
        if column.required and column.id not in row:
            msg = f"table {definition.id!r} row is missing {column.id!r}"
            raise ValueError(msg)
        if column.id in row:
            row[column.id] = _validate_cell_value(
                definition,
                column.id,
                row[column.id],
            )


def _validate_cell_value(
    definition: ParameterTableDefinition,
    column_id: str,
    value: ParameterPatchValue,
) -> ParameterPatchValue:
    column = next((item for item in definition.columns if item.id == column_id), None)
    if column is None:
        msg = f"table {definition.id!r} has no column {column_id!r}"
        raise ValueError(msg)
    try:
        return cast(
            "ParameterPatchValue",
            coerce_parameter_table_cell(
                table_id=definition.id,
                column=column,
                value=value,
                path=column_id,
            ),
        )
    except ParameterTableCellValidationError as error:
        raise ValueError(str(error)) from error


def _find_one_row(
    rows: list[dict[str, ParameterPatchValue]],
    definition: ParameterTableDefinition,
    key: dict[str, ParameterPatchValue],
) -> dict[str, ParameterPatchValue]:
    matches = _matching_rows(rows, key)
    if len(matches) != 1:
        msg = f"table {definition.id!r} key {key!r} matched {len(matches)} rows"
        raise ValueError(msg)
    return matches[0]


def _matching_rows(
    rows: list[dict[str, ParameterPatchValue]],
    key: dict[str, ParameterPatchValue],
) -> list[dict[str, ParameterPatchValue]]:
    return [
        row
        for row in rows
        if all(
            _cell_equal(row.get(column_id), value) for column_id, value in key.items()
        )
    ]


def _row_key(
    definition: ParameterTableDefinition,
    row: dict[str, ParameterPatchValue],
) -> dict[str, ParameterPatchValue]:
    return {column_id: row[column_id] for column_id in definition.primary_key}


def _rows_by_key(
    definition: ParameterTableDefinition,
    rows: list[dict[str, ParameterPatchValue]],
) -> dict[tuple[str, ...], dict[str, ParameterPatchValue]]:
    keyed: dict[tuple[str, ...], dict[str, ParameterPatchValue]] = {}
    for row in rows:
        key = tuple(_key_part(row[column_id]) for column_id in definition.primary_key)
        if key in keyed:
            msg = f"table {definition.id!r} has duplicate primary key {key!r}"
            raise ValueError(msg)
        keyed[key] = dict(row)
    return keyed


def _key_part(value: ParameterPatchValue) -> str:
    return parameter_table_key_part(value)


def _normalize_parameter_state_tables(
    catalog: ParameterCatalog,
    parameter_state: ParameterState,
) -> ParameterState:
    tables: list[ParameterTable] = []
    for table in parameter_state.tables:
        definition = catalog.table(table.id)
        tables.append(
            coerce_parameter_table(definition, table)
            if definition is not None
            else table.model_copy(deep=True)
        )
    return parameter_state.model_copy(update={"tables": tables}, deep=True)


def _quantity_value(value: ParameterPatchValue, *, path: str) -> Quantity:
    if not isinstance(value, Quantity):
        msg = f"{path} must be a quantity"
        raise ValueError(msg)
    return value


def _validate_quantity_unit(quantity: Quantity, unit: str, *, path: str) -> None:
    if not compatible_units(quantity.unit, unit):
        msg = f"{path} unit {quantity.unit!r} is incompatible with {unit!r}"
        raise ValueError(msg)


def _validate_scalar_safety(
    definition: ParameterDefinition,
    value: Quantity,
) -> None:
    if definition.safety_min is not None and _quantity_less(
        value,
        definition.safety_min,
    ):
        msg = f"parameter {definition.id!r} is below safety_min"
        raise ValueError(msg)
    if definition.safety_max is not None and _quantity_less(
        definition.safety_max,
        value,
    ):
        msg = f"parameter {definition.id!r} is above safety_max"
        raise ValueError(msg)


def _quantity_less(left: Quantity, right: Quantity) -> bool:
    if not compatible_units(left.unit, right.unit):
        msg = f"cannot compare units {left.unit!r} and {right.unit!r}"
        raise ValueError(msg)
    left_base = to_base_value(left.value, left.unit)
    right_base = to_base_value(right.value, right.unit)
    if left_base is None or right_base is None:
        right_converted = right.to(left.unit)
        return left.value < right_converted.value
    return left_base < right_base


def _assert_equal(
    left: ParameterPatchValue,
    right: ParameterPatchValue,
    *,
    path: str,
) -> None:
    if not _cell_equal(left, right):
        msg = f"stale parameter patch at {path}"
        raise ValueError(msg)


def _cell_equal(left: ParameterPatchValue, right: ParameterPatchValue) -> bool:
    if isinstance(left, Quantity) and isinstance(right, Quantity):
        if not compatible_units(left.unit, right.unit):
            return False
        left_base = to_base_value(left.value, left.unit)
        right_base = to_base_value(right.value, right.unit)
        if left_base is None or right_base is None:
            if left.unit != right.unit:
                return False
            return math.isclose(left.value, right.value, rel_tol=0.0, abs_tol=1e-12)
        return math.isclose(left_base, right_base, rel_tol=0.0, abs_tol=1e-12)
    return left == right


def _required[T](value: T | None) -> T:
    if value is None:
        raise AssertionError("validated field is unexpectedly missing")
    return value

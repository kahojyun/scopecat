"""Transient user intents for deriving a candidate parameter snapshot."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from scopecat.config.validation import (
    coerce_parameter_table_cell,
    coerce_stored_parameter_value,
    parameter_table_key_part,
)
from scopecat.kernel.value_types import Scalar, Series, Table
from scopecat.records.parameter import (
    ParameterAtomValue,
    ParameterCatalog,
    ParameterSnapshot,
    ScalarParameterValue,
    SeriesParameterValue,
    StoredParameterValue,
    TableParameterValue,
)
from scopecat.records.parameter_change import ParameterValueDelta


@dataclass(frozen=True, slots=True)
class ReplaceParameter:
    """Transient intent to replace one complete typed parameter value."""

    value: StoredParameterValue

    @property
    def parameter_id(self) -> str:
        return self.value.id


@dataclass(frozen=True, slots=True)
class UpdateParameterRows:
    """Transient intent to update one row selected by a table primary key."""

    parameter_id: str
    key: Mapping[str, ParameterAtomValue]
    values: Mapping[str, ParameterAtomValue]


@dataclass(frozen=True, slots=True)
class InsertParameterRows:
    """Transient intent to append rows to a table-shaped parameter."""

    parameter_id: str
    rows: Sequence[Mapping[str, ParameterAtomValue]]


@dataclass(frozen=True, slots=True)
class DeleteParameterRows:
    """Transient intent to delete one row selected by a table primary key."""

    parameter_id: str
    key: Mapping[str, ParameterAtomValue]


type ParameterUpdate = (
    ReplaceParameter | UpdateParameterRows | InsertParameterRows | DeleteParameterRows
)


def replace_scalar_parameter(
    parameter_id: str,
    value: ParameterAtomValue,
) -> ReplaceParameter:
    """Build a scalar replacement intent from a closed durable atom."""

    return ReplaceParameter(value=ScalarParameterValue(id=parameter_id, value=value))


def replace_series_parameter(
    parameter_id: str,
    items: Sequence[ParameterAtomValue],
) -> ReplaceParameter:
    """Build a complete series replacement intent."""

    return ReplaceParameter(
        value=SeriesParameterValue(id=parameter_id, items=tuple(items))
    )


def replace_table_parameter(
    parameter_id: str,
    rows: Sequence[Mapping[str, ParameterAtomValue]],
) -> ReplaceParameter:
    """Build a complete table replacement intent."""

    return ReplaceParameter(
        value=TableParameterValue(id=parameter_id, rows=tuple(rows))
    )


def update_parameter_rows(
    parameter_id: str,
    *,
    key: Mapping[str, ParameterAtomValue],
    values: Mapping[str, ParameterAtomValue],
) -> UpdateParameterRows:
    """Build a keyed row update intent.

    The mapping is recursively frozen by the durable table-value validator,
    while catalog-dependent checks happen when an analysis materializes it.
    """

    if not values:
        msg = "parameter row update values must be non-empty"
        raise ValueError(msg)
    frozen = TableParameterValue(id=parameter_id, rows=(key, values)).rows
    return UpdateParameterRows(
        parameter_id=parameter_id,
        key=frozen[0],
        values=frozen[1],
    )


def insert_parameter_rows(
    parameter_id: str,
    rows: Sequence[Mapping[str, ParameterAtomValue]],
) -> InsertParameterRows:
    """Build a table-row insertion intent."""

    if not rows:
        msg = "parameter row insertion requires at least one row"
        raise ValueError(msg)
    frozen = TableParameterValue(id=parameter_id, rows=tuple(rows)).rows
    return InsertParameterRows(parameter_id=parameter_id, rows=frozen)


def delete_parameter_rows(
    parameter_id: str,
    *,
    key: Mapping[str, ParameterAtomValue],
) -> DeleteParameterRows:
    """Build a keyed row deletion intent."""

    frozen = TableParameterValue(id=parameter_id, rows=(key,)).rows[0]
    return DeleteParameterRows(parameter_id=parameter_id, key=frozen)


def materialize_parameter_updates(
    *,
    catalog: ParameterCatalog,
    base: ParameterSnapshot,
    updates: Sequence[ParameterUpdate],
    candidate_id: str,
) -> tuple[ParameterSnapshot, tuple[ParameterValueDelta, ...]]:
    """Apply transient intents and return one authoritative candidate + delta."""

    if not updates:
        msg = "parameter change proposal requires at least one update"
        raise ValueError(msg)
    original = {value.id: value for value in base.values}
    selected = dict(original)
    order = [value.id for value in base.values]
    touched: list[str] = []
    for update in updates:
        parameter_id = update.parameter_id
        definition = catalog.get(parameter_id)
        if definition is None:
            msg = f"parameter {parameter_id!r} is not defined in the catalog"
            raise ValueError(msg)
        current = selected.get(parameter_id)
        if current is None:
            msg = f"parameter {parameter_id!r} is missing from the base snapshot"
            raise ValueError(msg)
        if parameter_id not in touched:
            touched.append(parameter_id)
        if isinstance(update, ReplaceParameter):
            replacement = update.value.model_copy(
                update={"metadata": current.metadata},
                deep=True,
            )
            _require_matching_shape(
                parameter_id=parameter_id,
                expected=definition.value_type,
                value=replacement,
            )
            selected[parameter_id] = replacement
            continue
        if not isinstance(definition.value_type, Table) or not isinstance(
            current, TableParameterValue
        ):
            msg = f"parameter {parameter_id!r} is not table-shaped"
            raise ValueError(msg)
        selected[parameter_id] = _apply_table_update(
            current=current,
            table_type=definition.value_type,
            update=update,
        )

    for parameter_id in touched:
        definition = catalog.get(parameter_id)
        assert definition is not None
        selected[parameter_id] = coerce_stored_parameter_value(
            definition,
            selected[parameter_id],
            path=("parameter_snapshot", "values", parameter_id),
        )
    candidate = ParameterSnapshot(
        id=candidate_id,
        values=tuple(selected[value_id] for value_id in order),
        metadata=base.metadata,
    )
    deltas = tuple(
        ParameterValueDelta(
            parameter_id=parameter_id,
            before=original[parameter_id],
            after=selected[parameter_id],
        )
        for parameter_id in touched
        if original[parameter_id] != selected[parameter_id]
    )
    if not deltas:
        msg = "parameter change proposal does not change the base snapshot"
        raise ValueError(msg)
    return candidate, deltas


def merge_candidate_parameter_snapshots(
    *,
    base: ParameterSnapshot,
    candidates: Sequence[tuple[ParameterSnapshot, Sequence[ParameterValueDelta]]],
    candidate_id: str,
) -> ParameterSnapshot:
    """Merge independently derived candidates and verify their review deltas.

    Candidate snapshots are authoritative. Deltas are checked projections of
    the actual base-to-candidate difference and are never replayed as commands.
    """

    base_values = {value.id: value for value in base.values}
    selected = dict(base_values)
    order = [value.id for value in base.values]
    touched: set[str] = set()
    for candidate, deltas in candidates:
        if candidate.metadata != base.metadata:
            msg = "candidate proposal cannot change parameter snapshot metadata"
            raise ValueError(msg)
        candidate_values = {value.id: value for value in candidate.values}
        if candidate_values.keys() != base_values.keys():
            msg = "candidate proposal must preserve the parameter value namespace"
            raise ValueError(msg)
        changed = {
            parameter_id
            for parameter_id in order
            if candidate_values[parameter_id] != base_values[parameter_id]
        }
        delta_by_id = {delta.parameter_id: delta for delta in deltas}
        if delta_by_id.keys() != changed:
            msg = "candidate proposal deltas do not describe its snapshot changes"
            raise ValueError(msg)
        overlap = touched & changed
        if overlap:
            msg = "candidate config proposals overlap on parameters: " + ", ".join(
                sorted(overlap)
            )
            raise ValueError(msg)
        for parameter_id in changed:
            delta = delta_by_id[parameter_id]
            if delta.before != base_values[parameter_id]:
                msg = (
                    "candidate proposal delta before value does not match source "
                    f"snapshot: {parameter_id}"
                )
                raise ValueError(msg)
            if delta.after != candidate_values[parameter_id]:
                msg = (
                    "candidate proposal delta after value does not match candidate "
                    f"snapshot: {parameter_id}"
                )
                raise ValueError(msg)
            selected[parameter_id] = candidate_values[parameter_id]
        touched.update(changed)
    return ParameterSnapshot(
        id=candidate_id,
        values=tuple(selected[value_id] for value_id in order),
        metadata=base.metadata,
    )


def _require_matching_shape(
    *,
    parameter_id: str,
    expected: Scalar | Series | Table,
    value: StoredParameterValue,
) -> None:
    matches = (
        (isinstance(expected, Scalar) and isinstance(value, ScalarParameterValue))
        or (isinstance(expected, Series) and isinstance(value, SeriesParameterValue))
        or (isinstance(expected, Table) and isinstance(value, TableParameterValue))
    )
    if not matches:
        msg = (
            f"parameter {parameter_id!r} replacement shape does not match "
            "its catalog definition"
        )
        raise ValueError(msg)


def _apply_table_update(
    *,
    current: TableParameterValue,
    table_type: Table,
    update: UpdateParameterRows | InsertParameterRows | DeleteParameterRows,
) -> TableParameterValue:
    if isinstance(update, InsertParameterRows):
        return TableParameterValue(
            id=current.id,
            rows=(*current.rows, *update.rows),
            metadata=current.metadata,
        )
    _require_complete_key(
        parameter_id=current.id,
        primary_key=table_type.primary_key,
        key=update.key,
    )
    key = _coerce_table_cells(
        parameter_id=current.id,
        table_type=table_type,
        values=update.key,
        path=("key",),
    )
    matches = [
        index
        for index, row in enumerate(current.rows)
        if _row_matches_key(
            parameter_id=current.id,
            table_type=table_type,
            row=row,
            key=key,
        )
    ]
    if not matches:
        msg = f"parameter table {current.id!r} has no row matching key"
        raise ValueError(msg)
    if len(matches) != 1:
        msg = f"parameter table {current.id!r} key matches multiple rows"
        raise ValueError(msg)
    selected_index = matches[0]
    if isinstance(update, DeleteParameterRows):
        rows = tuple(
            row for index, row in enumerate(current.rows) if index != selected_index
        )
    else:
        changed_key_columns = set(table_type.primary_key) & update.values.keys()
        if changed_key_columns:
            msg = (
                f"parameter table {current.id!r} row updates cannot change primary "
                "key columns: " + ", ".join(sorted(changed_key_columns))
            )
            raise ValueError(msg)
        values = _coerce_table_cells(
            parameter_id=current.id,
            table_type=table_type,
            values=update.values,
            path=("values",),
        )
        rows = tuple(
            (dict(row) | values) if index == selected_index else row
            for index, row in enumerate(current.rows)
        )
    return TableParameterValue(
        id=current.id,
        rows=rows,
        metadata=current.metadata,
    )


def _require_complete_key(
    *,
    parameter_id: str,
    primary_key: tuple[str, ...],
    key: Mapping[str, ParameterAtomValue],
) -> None:
    if not primary_key:
        msg = (
            f"parameter table {parameter_id!r} has no primary key; replace the "
            "complete table instead"
        )
        raise ValueError(msg)
    if set(key) != set(primary_key):
        msg = (
            f"parameter table {parameter_id!r} row key must contain exactly: "
            + ", ".join(primary_key)
        )
        raise ValueError(msg)


def _row_matches_key(
    *,
    parameter_id: str,
    table_type: Table,
    row: Mapping[str, ParameterAtomValue],
    key: Mapping[str, ParameterAtomValue],
) -> bool:
    if not key.keys() <= row.keys():
        return False
    normalized_row_key = _coerce_table_cells(
        parameter_id=parameter_id,
        table_type=table_type,
        values={column_id: row[column_id] for column_id in key},
        path=("current_row_key",),
    )
    return all(
        parameter_table_key_part(normalized_row_key[column_id])
        == parameter_table_key_part(value)
        for column_id, value in key.items()
    )


def _coerce_table_cells(
    *,
    parameter_id: str,
    table_type: Table,
    values: Mapping[str, ParameterAtomValue],
    path: tuple[str | int, ...],
) -> dict[str, ParameterAtomValue]:
    columns = {column.id: column for column in table_type.columns}
    unknown = sorted(values.keys() - columns.keys())
    if unknown:
        msg = (
            f"parameter table {parameter_id!r} update references unknown columns: "
            + ", ".join(unknown)
        )
        raise ValueError(msg)
    return {
        column_id: coerce_parameter_table_cell(
            parameter_id=parameter_id,
            column=columns[column_id],
            value=value,
            path=(*path, column_id),
        )
        for column_id, value in values.items()
    }


__all__ = [
    "DeleteParameterRows",
    "InsertParameterRows",
    "ParameterUpdate",
    "ReplaceParameter",
    "UpdateParameterRows",
    "delete_parameter_rows",
    "insert_parameter_rows",
    "materialize_parameter_updates",
    "merge_candidate_parameter_snapshots",
    "replace_scalar_parameter",
    "replace_series_parameter",
    "replace_table_parameter",
    "update_parameter_rows",
]

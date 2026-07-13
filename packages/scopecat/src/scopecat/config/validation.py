"""Validation for durable parameter values against unified value types."""

from __future__ import annotations

from typing import NoReturn, cast

from scopecat.kernel.value_identity import scalar_identity
from scopecat.kernel.value_types import (
    Bool,
    Entity,
    Float,
    Int,
    Quantity,
    Scalar,
    Series,
    String,
    Table,
    TableColumn,
)
from scopecat.kernel.value_validation import (
    ValuePath,
    ValueValidationError,
    coerce_literal,
)
from scopecat.records.parameter import (
    ParameterAtomValue,
    ParameterDefinition,
    ScalarParameterValue,
    SeriesParameterValue,
    StoredParameterValue,
    TableParameterValue,
)


class ParameterValueValidationError(ValueError):
    """A stored parameter value does not satisfy its catalog definition."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: ValuePath | None = None,
    ) -> None:
        self.code = code
        self.path = path
        super().__init__(message)


def coerce_parameter_atom(
    *,
    parameter_id: str,
    value_type: Scalar,
    value: object,
    path: ValuePath,
) -> ParameterAtomValue:
    """Validate and normalize one durable scalar atom."""

    try:
        return cast(
            "ParameterAtomValue",
            coerce_literal(value_type, value, path=path),
        )
    except ValueValidationError as error:
        atom = value_type.atom
        if isinstance(atom, Bool):
            label = "bool"
            code = "invalid_parameter_bool"
        elif isinstance(atom, Int):
            label = "int"
            code = "invalid_parameter_int"
        elif isinstance(atom, Float):
            label = "number"
            code = "invalid_parameter_number"
        elif isinstance(atom, String):
            label = "string"
            code = "invalid_parameter_string"
        elif isinstance(atom, Quantity):
            label = "quantity"
            code = (
                "incompatible_parameter_quantity_unit"
                if error.code == "incompatible_unit"
                else "invalid_parameter_quantity"
            )
        elif isinstance(atom, Entity):
            label = "entity"
            code = "invalid_parameter_entity"
        else:  # PersistableValueType rejects non-durable atoms.
            label = type(atom).__name__.lower()
            code = "invalid_parameter_value"
        msg = f"parameter {parameter_id} requires {label}: {error.reason}"
        raise ParameterValueValidationError(code, msg, path=error.path) from error


def coerce_stored_parameter_value(
    definition: ParameterDefinition,
    stored: StoredParameterValue,
    *,
    path: ValuePath,
) -> StoredParameterValue:
    """Validate and normalize one stored value using its catalog type."""

    value_type = definition.value_type
    if isinstance(value_type, Scalar):
        if not isinstance(stored, ScalarParameterValue):
            _raise_shape_mismatch(definition, stored, expected="scalar", path=path)
        return stored.model_copy(
            update={
                "value": coerce_parameter_atom(
                    parameter_id=definition.id,
                    value_type=value_type,
                    value=stored.value,
                    path=(*path, "value"),
                )
            }
        )
    if isinstance(value_type, Series):
        if not isinstance(stored, SeriesParameterValue):
            _raise_shape_mismatch(definition, stored, expected="series", path=path)
        _validate_length(
            len(stored.items),
            minimum=value_type.min_length,
            maximum=value_type.max_length,
            parameter_id=definition.id,
            shape="series",
            path=(*path, "items"),
        )
        return stored.model_copy(
            update={
                "items": tuple(
                    coerce_parameter_atom(
                        parameter_id=definition.id,
                        value_type=value_type.item_type,
                        value=item,
                        path=(*path, "items", index),
                    )
                    for index, item in enumerate(stored.items)
                )
            }
        )
    if not isinstance(stored, TableParameterValue):
        _raise_shape_mismatch(definition, stored, expected="table", path=path)
    return _coerce_table(definition, value_type, stored, path=path)


def coerce_parameter_table_cell(
    *,
    parameter_id: str,
    column: TableColumn,
    value: object,
    path: ValuePath,
) -> ParameterAtomValue:
    """Validate and normalize one typed parameter-table cell."""

    return coerce_parameter_atom(
        parameter_id=parameter_id,
        value_type=column.value_type,
        value=value,
        path=path,
    )


def _coerce_table(
    definition: ParameterDefinition,
    value_type: Table,
    stored: TableParameterValue,
    *,
    path: ValuePath,
) -> TableParameterValue:
    _validate_length(
        len(stored.rows),
        minimum=value_type.min_rows,
        maximum=value_type.max_rows,
        parameter_id=definition.id,
        shape="table",
        path=(*path, "rows"),
    )
    columns = {column.id: column for column in value_type.columns}
    required = {column.id for column in value_type.columns if column.required}
    normalized_rows: list[dict[str, ParameterAtomValue]] = []
    seen_keys: set[tuple[object, ...]] = set()
    for row_index, row in enumerate(stored.rows):
        row_path = (*path, "rows", row_index)
        missing = sorted(required - row.keys())
        if missing:
            msg = (
                f"parameter table {definition.id} row is missing columns: "
                + ", ".join(missing)
            )
            raise ParameterValueValidationError(
                "missing_parameter_table_columns",
                msg,
                path=row_path,
            )
        extra = sorted(row.keys() - columns.keys())
        if extra:
            msg = (
                f"parameter table {definition.id} row contains unknown columns: "
                + ", ".join(extra)
            )
            raise ParameterValueValidationError(
                "unknown_parameter_table_columns",
                msg,
                path=row_path,
            )
        normalized = {
            column_id: coerce_parameter_table_cell(
                parameter_id=definition.id,
                column=columns[column_id],
                value=value,
                path=(*row_path, column_id),
            )
            for column_id, value in row.items()
        }
        if value_type.primary_key:
            key = tuple(
                scalar_identity(normalized[column_id])
                for column_id in value_type.primary_key
            )
            if key in seen_keys:
                msg = (
                    f"parameter table {definition.id} has duplicate primary key {key!r}"
                )
                raise ParameterValueValidationError(
                    "duplicate_parameter_table_primary_key",
                    msg,
                    path=row_path,
                )
            seen_keys.add(key)
        normalized_rows.append(normalized)
    return stored.model_copy(update={"rows": normalized_rows})


def _raise_shape_mismatch(
    definition: ParameterDefinition,
    stored: StoredParameterValue,
    *,
    expected: str,
    path: ValuePath,
) -> NoReturn:
    msg = f"parameter {definition.id} requires {expected} shape, got {stored.shape}"
    raise ParameterValueValidationError(
        "parameter_shape_mismatch",
        msg,
        path=path,
    )


def _validate_length(
    length: int,
    *,
    minimum: int,
    maximum: int | None,
    parameter_id: str,
    shape: str,
    path: ValuePath,
) -> None:
    if length < minimum:
        msg = (
            f"parameter {parameter_id} {shape} has {length} items; minimum is {minimum}"
        )
        raise ParameterValueValidationError(
            "parameter_length_out_of_bounds",
            msg,
            path=path,
        )
    if maximum is not None and length > maximum:
        msg = (
            f"parameter {parameter_id} {shape} has {length} items; maximum is {maximum}"
        )
        raise ParameterValueValidationError(
            "parameter_length_out_of_bounds",
            msg,
            path=path,
        )


def parameter_table_key_part(value: object) -> str:
    """Build a stable, hashable identity component from a normalized cell."""

    return repr(scalar_identity(value))


__all__ = [
    "ParameterValueValidationError",
    "coerce_parameter_atom",
    "coerce_parameter_table_cell",
    "coerce_stored_parameter_value",
    "parameter_table_key_part",
]

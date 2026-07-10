"""Shared validation for cells in persisted parameter tables."""

from __future__ import annotations

from scopecat.models.parameter import (
    ParameterTable,
    ParameterTableColumn,
    ParameterTableDefinition,
)
from scopecat.models.parameter import (
    Quantity as QuantityValue,
)
from scopecat.units import to_base_value, unit_kind
from scopecat.value_types import (
    Bool,
    Float,
    Int,
    Quantity,
    String,
)
from scopecat.value_validation import ValueValidationError, coerce_literal


class ParameterTableCellValidationError(ValueError):
    """A parameter table cell does not satisfy its declared scalar type."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def validate_parameter_table_cell(
    *,
    table_id: str,
    column: ParameterTableColumn,
    value: object,
    path: str,
) -> None:
    """Validate one cell with the same rules used by authoring inputs."""

    coerce_parameter_table_cell(
        table_id=table_id,
        column=column,
        value=value,
        path=path,
    )


def coerce_parameter_table_cell(
    *,
    table_id: str,
    column: ParameterTableColumn,
    value: object,
    path: str,
) -> object:
    """Validate and normalize one persisted parameter table cell."""

    try:
        return coerce_literal(column.value_type, value, path=path)
    except ValueValidationError as error:
        atom = column.value_type.atom
        code: str
        label: str
        if isinstance(atom, Bool):
            code = "invalid_parameter_table_bool"
            label = "bool"
        elif isinstance(atom, Int):
            code = "invalid_parameter_table_int"
            label = "int"
        elif isinstance(atom, Float):
            code = "invalid_parameter_table_number"
            label = "number"
        elif isinstance(atom, String):
            code = "invalid_parameter_table_string"
            label = "string"
        elif isinstance(atom, Quantity):
            label = "quantity"
            code = (
                "incompatible_parameter_table_quantity_unit"
                if error.code == "incompatible_unit"
                else "invalid_parameter_table_quantity"
            )
        else:  # ParameterTableColumn rejects non-persistable atom types.
            code = "invalid_parameter_table_cell"
            label = type(atom).__name__.lower()
        msg = (
            f"parameter table {table_id} column {column.id} requires {label}: "
            f"{error.reason}"
        )
        raise ParameterTableCellValidationError(code, msg) from error


def coerce_parameter_table(
    definition: ParameterTableDefinition,
    table: ParameterTable,
) -> ParameterTable:
    """Return a fully validated table with every known cell normalized."""

    columns = {column.id: column for column in definition.columns}
    required = {column.id for column in definition.columns if column.required}
    rows: list[dict[str, object]] = []
    for row_index, row in enumerate(table.rows):
        path = f"{table.id}.rows.{row_index}"
        missing = sorted(required - row.keys())
        if missing:
            msg = f"parameter table {table.id} row is missing columns: " + ", ".join(
                missing
            )
            raise ParameterTableCellValidationError(
                "missing_parameter_table_columns",
                msg,
            )
        extra = sorted(row.keys() - columns.keys())
        if extra:
            msg = (
                f"parameter table {table.id} row contains unknown columns: "
                + ", ".join(extra)
            )
            raise ParameterTableCellValidationError(
                "unknown_parameter_table_columns",
                msg,
            )
        rows.append(
            {
                column_id: coerce_parameter_table_cell(
                    table_id=table.id,
                    column=columns[column_id],
                    value=value,
                    path=f"{path}.{column_id}",
                )
                for column_id, value in row.items()
            }
        )
    return table.model_copy(update={"rows": rows}, deep=True)


def parameter_table_key_part(value: object) -> str:
    """Build a stable, hashable identity component from a normalized cell."""

    if isinstance(value, QuantityValue):
        base_value = to_base_value(value.value, value.unit)
        if base_value is not None:
            return f"quantity:{unit_kind(value.unit)}:{base_value!r}"
        return f"quantity:{value.unit}:{value.value!r}"
    if isinstance(value, bool):
        return f"bool:{value!r}"
    if isinstance(value, int):
        return f"int:{value!r}"
    if isinstance(value, float):
        normalized = 0.0 if value == 0.0 else value
        return f"float:{normalized!r}"
    if isinstance(value, str):
        return f"string:{value!r}"
    return f"{type(value).__name__}:{value!r}"


__all__ = [
    "ParameterTableCellValidationError",
    "coerce_parameter_table",
    "coerce_parameter_table_cell",
    "parameter_table_key_part",
    "validate_parameter_table_cell",
]

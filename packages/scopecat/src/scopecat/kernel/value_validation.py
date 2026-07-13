"""Runtime coercion for the orthogonal value type system."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import cast

from pydantic import ValidationError

from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.problems import LocationPathItem
from scopecat.kernel.units import compatible_units, unit_kind
from scopecat.kernel.value_identity import ScalarIdentity, scalar_identity
from scopecat.kernel.value_types import (
    AtomType,
    Bool,
    Entity,
    Float,
    Int,
    Payload,
    Quantity,
    Record,
    Scalar,
    Series,
    String,
    Table,
    ValueType,
)
from scopecat.records.entity import EntityRef, normalize_entity_metadata
from scopecat.records.parameter import Quantity as QuantityValue

type ValuePath = tuple[LocationPathItem, ...]


def format_value_path(path: ValuePath) -> str:
    """Render a structured value path for human-readable exception text."""

    if not path:
        return ""
    selected = ""
    for index, item in enumerate(path):
        if isinstance(item, int):
            selected += f"[{item}]"
        elif index == 0 or item.isidentifier():
            selected += item if index == 0 else f".{item}"
        else:
            selected += f"[{item!r}]"
    return selected


class ValueValidationError(ValueError):
    """A literal does not satisfy a value type."""

    def __init__(
        self,
        path: ValuePath,
        reason: str,
        *,
        code: str = "invalid_value",
    ) -> None:
        self.path = path
        self.reason = reason
        self.code = code
        rendered_path = format_value_path(path)
        super().__init__(f"{rendered_path}: {reason}" if rendered_path else reason)


def coerce_literal(
    value_type: ValueType,
    value: object,
    *,
    path: ValuePath = ("value",),
) -> object:
    """Validate and normalize a Python literal for ``value_type``.

    Collections normalize to tuples, records and rows normalize to dictionaries,
    numeric float values normalize to ``float``, and entity strings normalize to
    :class:`~scopecat.records.entity.EntityRef` objects. Opaque payloads normalize
    to transient, schema-tagged runtime wrappers.
    """

    if value is None:
        if isinstance(value_type, Scalar) and value_type.nullable:
            return None
        raise ValueValidationError(path, "value must not be null")
    if isinstance(value_type, Scalar):
        return _coerce_atom(value_type.atom, value, path=path)
    if isinstance(value_type, Series):
        return _coerce_series(value_type, value, path=path)
    return _coerce_table(value_type, value, path=path)


def validate_literal(
    value_type: ValueType,
    value: object,
    *,
    path: ValuePath = ("value",),
) -> None:
    """Raise :class:`ValueValidationError` if a literal is incompatible."""

    coerce_literal(value_type, value, path=path)


def _coerce_atom(atom: AtomType, value: object, *, path: ValuePath) -> object:
    if isinstance(atom, Bool):
        if not isinstance(value, bool):
            raise ValueValidationError(path, f"expected bool, got {value!r}")
        return value
    if isinstance(atom, Int):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueValidationError(path, f"expected int, got {value!r}")
        _validate_numeric_value(value, atom.minimum, atom.maximum, path=path)
        return value
    if isinstance(atom, Float):
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise ValueValidationError(path, f"expected float, got {value!r}")
        numeric_value = float(value)
        if atom.finite and not math.isfinite(numeric_value):
            raise ValueValidationError(path, "expected a finite float")
        _validate_numeric_value(
            numeric_value,
            atom.minimum,
            atom.maximum,
            path=path,
        )
        return numeric_value
    if isinstance(atom, String):
        return _coerce_string(atom, value, path=path)
    if isinstance(atom, Quantity):
        return _coerce_quantity(atom, value, path=path)
    if isinstance(atom, Entity):
        return _coerce_entity(atom, value, path=path)
    if isinstance(atom, Record):
        return _coerce_record(atom, value, path=path)
    return _coerce_payload(atom, value, path=path)


def _coerce_string(atom: String, value: object, *, path: ValuePath) -> str:
    if not isinstance(value, str):
        raise ValueValidationError(path, f"expected string, got {value!r}")
    length = len(value)
    _validate_collection_length(
        length,
        atom.min_length,
        atom.max_length,
        path=path,
        label="string",
    )
    if atom.pattern is not None and re.fullmatch(atom.pattern, value) is None:
        raise ValueValidationError(
            path,
            f"string does not match pattern {atom.pattern!r}",
        )
    if atom.choices is not None and value not in atom.choices:
        raise ValueValidationError(
            path,
            f"string must be one of {', '.join(repr(item) for item in atom.choices)}",
        )
    return value


def _coerce_quantity(
    atom: Quantity,
    value: object,
    *,
    path: ValuePath,
) -> QuantityValue:
    selected: QuantityValue
    if isinstance(value, QuantityValue):
        selected = value
    elif isinstance(value, int | float) and not isinstance(value, bool):
        if atom.unit is None:
            raise ValueValidationError(
                path,
                "numeric quantity literal requires a declared unit",
            )
        selected = QuantityValue(value=float(value), unit=atom.unit)
    elif isinstance(value, Mapping):
        try:
            selected = QuantityValue.model_validate(value)
        except ValidationError as error:
            raise ValueValidationError(path, f"invalid quantity: {error}") from error
    else:
        raise ValueValidationError(path, f"expected quantity, got {value!r}")

    expected_dimension = atom.dimension or (
        unit_kind(atom.unit) if atom.unit is not None else None
    )
    if (
        expected_dimension is not None
        and unit_kind(selected.unit) != expected_dimension
    ):
        raise ValueValidationError(
            path,
            "quantity must use dimension "
            f"{expected_dimension!r}, got {selected.unit!r}",
            code="incompatible_unit",
        )
    if atom.unit is not None:
        if not compatible_units(atom.unit, selected.unit):
            raise ValueValidationError(
                path,
                f"quantity must use a unit compatible with {atom.unit!r}",
                code="incompatible_unit",
            )
        if selected.unit != atom.unit:
            try:
                selected = selected.to(atom.unit)
            except ValueError as error:
                raise ValueValidationError(
                    path,
                    str(error),
                    code="incompatible_unit",
                ) from error
    if atom.finite and not math.isfinite(selected.value):
        raise ValueValidationError(path, "expected a finite quantity")
    _validate_numeric_value(
        selected.value,
        atom.minimum,
        atom.maximum,
        path=path,
    )
    return selected


def _coerce_entity(atom: Entity, value: object, *, path: ValuePath) -> EntityRef:
    if isinstance(value, EntityRef):
        try:
            selected = value.model_copy(
                update={"metadata": normalize_entity_metadata(value.metadata)},
                deep=True,
            )
        except ValueError as error:
            raise ValueValidationError(path, f"invalid entity: {error}") from error
    elif isinstance(value, str):
        selected = EntityRef(id=value, kind=atom.entity_kind)
    elif isinstance(value, Mapping):
        try:
            selected = EntityRef.model_validate(value)
        except ValidationError as error:
            raise ValueValidationError(path, f"invalid entity: {error}") from error
    else:
        raise ValueValidationError(path, f"expected entity reference, got {value!r}")
    if not selected.id:
        raise ValueValidationError(path, "entity id must be non-empty")
    if atom.entity_kind is None:
        return selected
    if selected.kind is not None and selected.kind != atom.entity_kind:
        raise ValueValidationError(
            path,
            f"entity must have kind {atom.entity_kind!r}, got {selected.kind!r}",
        )
    if selected.kind is None:
        return selected.model_copy(update={"kind": atom.entity_kind})
    return selected


def _coerce_record(
    atom: Record,
    value: object,
    *,
    path: ValuePath,
) -> dict[str, object]:
    mapping = _string_mapping(value, path=path, label="record")
    fields = {field.id: field for field in atom.fields}
    missing = [
        field.id for field in atom.fields if field.required and field.id not in mapping
    ]
    if missing:
        raise ValueValidationError(
            path,
            "record is missing required fields: " + ", ".join(missing),
        )
    extra = sorted(set(mapping) - set(fields))
    if extra and not atom.allow_extra_fields:
        raise ValueValidationError(
            path,
            "record contains unknown fields: " + ", ".join(extra),
        )
    result = {
        field_id: coerce_literal(
            field.value_type,
            mapping[field_id],
            path=(*path, field_id),
        )
        for field_id, field in fields.items()
        if field_id in mapping
    }
    if atom.allow_extra_fields:
        result.update({field_id: mapping[field_id] for field_id in extra})
    return result


def _coerce_payload(atom: Payload, value: object, *, path: ValuePath) -> PayloadValue:
    if isinstance(value, PayloadValue):
        if value.schema_id != atom.schema_id:
            raise ValueValidationError(
                path,
                f"expected payload {atom.schema_id!r}, got {value.schema_id!r}",
            )
        selected_payload = value.payload
    else:
        selected_payload = value
    if atom.python_type is not None and not isinstance(
        selected_payload,
        atom.python_type,
    ):
        expected_name = _python_type_name(atom.python_type)
        raise ValueValidationError(
            path,
            f"payload {atom.schema_id!r} expects {expected_name}, "
            f"got {selected_payload!r}",
        )
    return PayloadValue(schema_id=atom.schema_id, payload=selected_payload)


def _coerce_series(
    value_type: Series,
    value: object,
    *,
    path: ValuePath,
) -> tuple[object, ...]:
    sequence = _sequence(value, path=path, label="series")
    _validate_collection_length(
        len(sequence),
        value_type.min_length,
        value_type.max_length,
        path=path,
        label="series",
    )
    return tuple(
        coerce_literal(value_type.item_type, item, path=(*path, index))
        for index, item in enumerate(sequence)
    )


def _coerce_table(
    value_type: Table,
    value: object,
    *,
    path: ValuePath,
) -> tuple[dict[str, object], ...]:
    rows = _sequence(value, path=path, label="table")
    _validate_collection_length(
        len(rows),
        value_type.min_rows,
        value_type.max_rows,
        path=path,
        label="table",
    )
    columns = {column.id: column for column in value_type.columns}
    result: list[dict[str, object]] = []
    primary_keys: dict[tuple[ScalarIdentity, ...], int] = {}
    for index, raw_row in enumerate(rows):
        row_path = (*path, index)
        row = _string_mapping(raw_row, path=row_path, label="table row")
        missing = [
            column.id
            for column in value_type.columns
            if column.required and column.id not in row
        ]
        if missing:
            raise ValueValidationError(
                row_path,
                "table row is missing required columns: " + ", ".join(missing),
            )
        extra = sorted(set(row) - set(columns))
        if extra and not value_type.allow_extra_columns:
            raise ValueValidationError(
                row_path,
                "table row contains unknown columns: " + ", ".join(extra),
            )
        selected = {
            column_id: coerce_literal(
                column.value_type,
                row[column_id],
                path=(*row_path, column_id),
            )
            for column_id, column in columns.items()
            if column_id in row
        }
        if value_type.allow_extra_columns:
            selected.update({column_id: row[column_id] for column_id in extra})
        if value_type.primary_key:
            key = tuple(selected[column_id] for column_id in value_type.primary_key)
            identity = tuple(scalar_identity(value) for value in key)
            duplicate_index = primary_keys.get(identity)
            if duplicate_index is not None:
                raise ValueValidationError(
                    row_path,
                    f"table primary key {key!r} duplicates row {duplicate_index}",
                )
            primary_keys[identity] = index
        result.append(selected)
    return tuple(result)


def _validate_numeric_value(
    value: float,
    minimum: float | None,
    maximum: float | None,
    *,
    path: ValuePath,
) -> None:
    if minimum is not None and value < minimum:
        raise ValueValidationError(path, f"value must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueValidationError(path, f"value must be at most {maximum}")


def _validate_collection_length(
    length: int,
    minimum: int,
    maximum: int | None,
    *,
    path: ValuePath,
    label: str,
) -> None:
    if length < minimum:
        raise ValueValidationError(
            path,
            f"{label} must contain at least {minimum} item(s)",
        )
    if maximum is not None and length > maximum:
        raise ValueValidationError(
            path,
            f"{label} must contain at most {maximum} item(s)",
        )


def _string_mapping(
    value: object,
    *,
    path: ValuePath,
    label: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueValidationError(path, f"expected {label} mapping, got {value!r}")
    mapping = cast("Mapping[object, object]", value)
    if not all(isinstance(key, str) for key in mapping):
        raise ValueValidationError(path, f"{label} keys must be strings")
    return cast("Mapping[str, object]", mapping)


def _sequence(
    value: object,
    *,
    path: ValuePath,
    label: str,
) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise ValueValidationError(path, f"expected {label} sequence, got {value!r}")
    return cast("Sequence[object]", value)


def _python_type_name(
    value: type[object] | tuple[type[object], ...],
) -> str:
    if isinstance(value, tuple):
        return " or ".join(item.__name__ for item in value)
    return value.__name__


__all__ = [
    "ValuePath",
    "ValueValidationError",
    "coerce_literal",
    "format_value_path",
    "validate_literal",
]

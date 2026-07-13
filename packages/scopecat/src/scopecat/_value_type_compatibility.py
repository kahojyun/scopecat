"""Shared compatibility and literal inference for first-class value types."""

from __future__ import annotations

from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity as QuantityValue
from scopecat.models.value import PayloadValue
from scopecat.units import compatible_units, unit_kind
from scopecat.value_types import (
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
from scopecat.value_validation import ValuePath, ValueValidationError


def require_assignable(
    source: ValueType,
    target: ValueType,
    *,
    path: ValuePath,
) -> None:
    """Require every value admitted by ``source`` to be accepted by ``target``."""

    if is_assignable(source, target):
        return
    raise ValueValidationError(
        path,
        f"expected {describe_value_type(target)}, got {describe_value_type(source)}",
        code="incompatible_value_type",
    )


def is_assignable(source: ValueType, target: ValueType) -> bool:
    """Return whether a typed producer can safely feed a typed consumer."""

    if isinstance(source, Scalar) and isinstance(target, Scalar):
        return _scalar_assignable(source, target)
    if isinstance(source, Series) and isinstance(target, Series):
        return _scalar_assignable(
            source.item_type, target.item_type
        ) and _range_is_subset(
            source.min_length,
            source.max_length,
            target.min_length,
            target.max_length,
        )
    if isinstance(source, Table) and isinstance(target, Table):
        return _table_assignable(source, target)
    return False


def describe_value_type(value_type: ValueType) -> str:
    if isinstance(value_type, Scalar):
        nullable = "?" if value_type.nullable else ""
        return f"Scalar[{_describe_atom(value_type.atom)}]{nullable}"
    if isinstance(value_type, Series):
        return f"Series[{describe_value_type(value_type.item_type)}]"
    columns = ", ".join(
        f"{column.id}: {describe_value_type(column.value_type)}"
        for column in value_type.columns
    )
    return f"Table{{{columns}}}"


def atom_is_assignable(source: AtomType, target: AtomType) -> bool:
    """Return whether a scalar atom can safely feed another scalar atom."""

    return _atom_assignable(source, target)


def literal_scalar_type(value: object) -> Scalar:
    """Infer the narrow scalar type of one closed literal."""

    return _literal_scalar_type(value)


def _scalar_assignable(source: Scalar, target: Scalar) -> bool:
    if source.nullable and not target.nullable:
        return False
    return _atom_assignable(source.atom, target.atom)


def _atom_assignable(source: AtomType, target: AtomType) -> bool:
    if type(source) is not type(target):
        return False
    if isinstance(source, Bool) and isinstance(target, Bool):
        return True
    if isinstance(source, Int) and isinstance(target, Int):
        return _numeric_constraints_are_subset(source, target)
    if isinstance(source, Float) and isinstance(target, Float):
        return (not target.finite or source.finite) and _numeric_constraints_are_subset(
            source, target
        )
    if isinstance(source, String) and isinstance(target, String):
        if not _range_is_subset(
            source.min_length,
            source.max_length,
            target.min_length,
            target.max_length,
        ):
            return False
        if target.pattern is not None and source.pattern != target.pattern:
            return False
        if target.choices is not None:
            return source.choices is not None and set(source.choices) <= set(
                target.choices
            )
        return True
    if isinstance(source, Quantity) and isinstance(target, Quantity):
        source_dimension = source.dimension or (
            unit_kind(source.unit) if source.unit is not None else None
        )
        target_dimension = target.dimension or (
            unit_kind(target.unit) if target.unit is not None else None
        )
        if target_dimension is not None and source_dimension != target_dimension:
            return False
        if (
            source.unit is not None
            and target.unit is not None
            and not compatible_units(source.unit, target.unit)
        ):
            return False
        if target.finite and not source.finite:
            return False
        source_minimum, source_maximum = _quantity_bounds_in_target_unit(
            source,
            target,
        )
        return _bounds_are_subset(
            source_minimum,
            source_maximum,
            target.minimum,
            target.maximum,
        )
    if isinstance(source, Entity) and isinstance(target, Entity):
        return target.entity_kind is None or source.entity_kind == target.entity_kind
    if isinstance(source, Payload) and isinstance(target, Payload):
        return source.schema_id == target.schema_id and _python_type_assignable(
            source.python_type,
            target.python_type,
        )
    if isinstance(source, Record) and isinstance(target, Record):
        return _record_assignable(source, target)
    return False


def _table_assignable(source: Table, target: Table) -> bool:
    if not _range_is_subset(
        source.min_rows,
        source.max_rows,
        target.min_rows,
        target.max_rows,
    ):
        return False
    source_columns = {column.id: column for column in source.columns}
    target_columns = {column.id: column for column in target.columns}
    for target_column in target.columns:
        source_column = source_columns.get(target_column.id)
        if source_column is None:
            if target_column.required:
                return False
            continue
        if target_column.required and not source_column.required:
            return False
        if not _scalar_assignable(source_column.value_type, target_column.value_type):
            return False
    if not target.allow_extra_columns and (
        source.allow_extra_columns or not set(source_columns) <= set(target_columns)
    ):
        return False
    if target.primary_key:
        if not source.primary_key:
            return False
        if not set(source.primary_key) <= set(target.primary_key):
            return False
    return True


def _record_assignable(source: Record, target: Record) -> bool:
    source_fields = {field.id: field for field in source.fields}
    target_fields = {field.id: field for field in target.fields}
    for target_field in target.fields:
        source_field = source_fields.get(target_field.id)
        if source_field is None:
            if target_field.required:
                return False
            continue
        if target_field.required and not source_field.required:
            return False
        if not is_assignable(source_field.value_type, target_field.value_type):
            return False
    return target.allow_extra_fields or (
        not source.allow_extra_fields and set(source_fields) <= set(target_fields)
    )


def _numeric_constraints_are_subset(source: Int | Float, target: Int | Float) -> bool:
    return _bounds_are_subset(
        source.minimum,
        source.maximum,
        target.minimum,
        target.maximum,
    )


def _bounds_are_subset(
    source_minimum: float | None,
    source_maximum: float | None,
    target_minimum: float | None,
    target_maximum: float | None,
) -> bool:
    if target_minimum is not None and (
        source_minimum is None or source_minimum < target_minimum
    ):
        return False
    return not (
        target_maximum is not None
        and (source_maximum is None or source_maximum > target_maximum)
    )


def _range_is_subset(
    source_minimum: int,
    source_maximum: int | None,
    target_minimum: int,
    target_maximum: int | None,
) -> bool:
    return source_minimum >= target_minimum and not (
        target_maximum is not None
        and (source_maximum is None or source_maximum > target_maximum)
    )


def _quantity_bounds_in_target_unit(
    source: Quantity,
    target: Quantity,
) -> tuple[float | None, float | None]:
    if source.unit is None or target.unit is None or source.unit == target.unit:
        return source.minimum, source.maximum
    source_unit = source.unit
    target_unit = target.unit

    def convert(value: float | None) -> float | None:
        if value is None:
            return None
        return QuantityValue(value=value, unit=source_unit).to(target_unit).value

    return convert(source.minimum), convert(source.maximum)


def _python_type_assignable(
    source: type[object] | tuple[type[object], ...] | None,
    target: type[object] | tuple[type[object], ...] | None,
) -> bool:
    if target is None:
        return True
    if source is None:
        return False
    source_types = source if isinstance(source, tuple) else (source,)
    target_types = target if isinstance(target, tuple) else (target,)
    return all(
        any(issubclass(source_type, target_type) for target_type in target_types)
        for source_type in source_types
    )


def _literal_scalar_type(value: object) -> Scalar:
    if value is None:
        return Scalar(String(), nullable=True)
    if isinstance(value, bool):
        return Scalar(Bool())
    if isinstance(value, int):
        return Scalar(Int(minimum=value, maximum=value))
    if isinstance(value, float):
        return Scalar(Float(minimum=value, maximum=value))
    if isinstance(value, str):
        return Scalar(String(min_length=len(value), max_length=len(value)))
    if isinstance(value, QuantityValue):
        return Scalar(
            Quantity(unit=value.unit, minimum=value.value, maximum=value.value)
        )
    if isinstance(value, EntityRef):
        return Scalar(Entity(entity_kind=value.kind))
    if isinstance(value, PayloadValue):
        return Scalar(Payload(value.schema_id))
    return Scalar(Payload(type(value).__qualname__, python_type=type(value)))


def _describe_atom(atom: AtomType) -> str:
    if isinstance(atom, Quantity):
        constraint = atom.unit or atom.dimension
        return f"Quantity[{constraint}]" if constraint is not None else "Quantity"
    if isinstance(atom, Entity):
        return (
            f"Entity[{atom.entity_kind}]" if atom.entity_kind is not None else "Entity"
        )
    if isinstance(atom, Payload):
        return f"Payload[{atom.schema_id}]"
    if isinstance(atom, Record):
        return "Record"
    return type(atom).__name__


__all__ = [
    "atom_is_assignable",
    "describe_value_type",
    "is_assignable",
    "literal_scalar_type",
    "require_assignable",
]

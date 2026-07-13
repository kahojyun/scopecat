"""Orthogonal value types shared by authoring and persisted schemas.

Shape and scalar content are deliberately independent:

* :class:`Scalar`, :class:`Series`, and :class:`Table` describe shape.
* :class:`Bool`, :class:`Int`, :class:`Float`, :class:`String`,
  :class:`Quantity`, :class:`Entity`, :class:`Record`, and :class:`Payload`
  describe scalar content.

This module contains definitions only. Runtime literal coercion lives in
``scopecat.kernel.value_validation`` so schema models can depend on these types
without depending on authoring or creating model import cycles.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

from scopecat.kernel.units import is_supported_unit, unit_kind


@dataclass(frozen=True, slots=True)
class Bool:
    """Boolean scalar content."""


@dataclass(frozen=True, slots=True)
class Int:
    """Integral scalar content with optional inclusive bounds."""

    minimum: int | None = None
    maximum: int | None = None

    def __post_init__(self) -> None:
        _validate_bounds(self.minimum, self.maximum, label="Int")


@dataclass(frozen=True, slots=True)
class Float:
    """Numeric scalar content with optional inclusive bounds."""

    minimum: float | None = None
    maximum: float | None = None
    finite: bool = True

    def __post_init__(self) -> None:
        _validate_bounds(self.minimum, self.maximum, label="Float")


@dataclass(frozen=True, slots=True)
class String:
    """String scalar content with length, pattern, or choice constraints."""

    min_length: int = 0
    max_length: int | None = None
    pattern: str | None = None
    choices: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        _validate_length_bounds(
            self.min_length,
            self.max_length,
            minimum_name="min_length",
            maximum_name="max_length",
            label="String",
        )
        if self.pattern is not None:
            try:
                re.compile(self.pattern)
            except re.error as error:
                msg = f"String pattern is invalid: {error}"
                raise ValueError(msg) from error
        if self.choices is not None:
            if not self.choices:
                msg = "String choices must not be empty"
                raise ValueError(msg)
            if len(set(self.choices)) != len(self.choices):
                msg = "String choices must be unique"
                raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Quantity:
    """Quantity content constrained by dimension, unit, and numeric bounds.

    Bounds are expressed in ``unit``. Consequently bounded quantities require
    an explicit unit, while an unbounded type may constrain only the dimension.
    """

    dimension: str | None = None
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    finite: bool = True

    def __post_init__(self) -> None:
        if self.unit is not None and not is_supported_unit(self.unit):
            msg = f"unsupported quantity unit: {self.unit}"
            raise ValueError(msg)
        if (
            self.unit is not None
            and self.dimension is not None
            and unit_kind(self.unit) != self.dimension
        ):
            msg = (
                f"quantity unit {self.unit!r} does not belong to dimension "
                f"{self.dimension!r}"
            )
            raise ValueError(msg)
        if (self.minimum is not None or self.maximum is not None) and self.unit is None:
            msg = "bounded Quantity requires an explicit unit"
            raise ValueError(msg)
        _validate_bounds(self.minimum, self.maximum, label="Quantity")


@dataclass(frozen=True, slots=True)
class Entity:
    """Entity reference content, optionally constrained by domain kind."""

    entity_kind: str | None = None

    def __post_init__(self) -> None:
        if self.entity_kind is not None and not self.entity_kind:
            msg = "Entity entity_kind must be non-empty when provided"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class RecordField:
    """One structurally typed record field."""

    id: str
    value_type: ValueType
    required: bool = True

    def __post_init__(self) -> None:
        _validate_id(self.id, label="record field")


@dataclass(frozen=True, slots=True)
class Record:
    """Structured scalar content with recursively typed fields."""

    fields: tuple[RecordField, ...]
    allow_extra_fields: bool = False

    def __post_init__(self) -> None:
        _validate_unique_ids(
            (field.id for field in self.fields),
            label="record fields",
        )


@dataclass(frozen=True, slots=True)
class Payload:
    """Opaque scalar content identified by a domain-owned schema id."""

    schema_id: str
    python_type: type[object] | tuple[type[object], ...] | None = None

    def __post_init__(self) -> None:
        _validate_id(self.schema_id, label="payload schema")
        if isinstance(self.python_type, tuple) and not self.python_type:
            msg = "Payload python_type tuple must not be empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Route:
    """Point-local resource route supplied explicitly to a compute function."""

    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_unique_ids(self.capabilities, label="route capabilities")


type AtomType = Bool | Int | Float | String | Quantity | Entity | Record | Payload


@dataclass(frozen=True, slots=True)
class Scalar:
    """A single atom, optionally nullable."""

    atom: AtomType
    nullable: bool = False


@dataclass(frozen=True, slots=True)
class Series:
    """An ordered one-dimensional collection of scalar values."""

    item_type: Scalar
    min_length: int = 0
    max_length: int | None = None

    def __post_init__(self) -> None:
        _validate_length_bounds(
            self.min_length,
            self.max_length,
            minimum_name="min_length",
            maximum_name="max_length",
            label="Series",
        )


@dataclass(frozen=True, slots=True)
class TableColumn:
    """One scalar column in a table type."""

    id: str
    value_type: Scalar
    required: bool = True

    def __post_init__(self) -> None:
        _validate_id(self.id, label="table column")


@dataclass(frozen=True, slots=True)
class Table:
    """A row collection with structural columns and an optional primary key."""

    columns: tuple[TableColumn, ...]
    primary_key: tuple[str, ...] = ()
    min_rows: int = 0
    max_rows: int | None = None
    allow_extra_columns: bool = False

    def __post_init__(self) -> None:
        _validate_unique_ids(
            (column.id for column in self.columns),
            label="table columns",
        )
        _validate_length_bounds(
            self.min_rows,
            self.max_rows,
            minimum_name="min_rows",
            maximum_name="max_rows",
            label="Table",
        )
        if len(set(self.primary_key)) != len(self.primary_key):
            msg = "Table primary_key must not contain duplicates"
            raise ValueError(msg)
        columns = {column.id: column for column in self.columns}
        missing = [
            column_id for column_id in self.primary_key if column_id not in columns
        ]
        if missing:
            msg = "Table primary_key references unknown columns: " + ", ".join(missing)
            raise ValueError(msg)
        for column_id in self.primary_key:
            column = columns[column_id]
            if not column.required or column.value_type.nullable:
                msg = (
                    f"Table primary key column {column_id!r} must be required "
                    "and non-null"
                )
                raise ValueError(msg)
            if isinstance(column.value_type.atom, Record | Payload):
                msg = (
                    f"Table primary key column {column_id!r} must use a primitive, "
                    "quantity, or entity atom"
                )
                raise ValueError(msg)
            if isinstance(column.value_type.atom, Float | Quantity) and not (
                column.value_type.atom.finite
            ):
                msg = (
                    f"Table primary key column {column_id!r} must guarantee "
                    "finite numeric values"
                )
                raise ValueError(msg)


type ValueType = Scalar | Series | Table


def _validate_bounds(
    minimum: float | None,
    maximum: float | None,
    *,
    label: str,
) -> None:
    if any(
        isinstance(bound, float) and not math.isfinite(bound)
        for bound in (minimum, maximum)
    ):
        msg = f"{label} bounds must be finite"
        raise ValueError(msg)
    if minimum is not None and maximum is not None and minimum > maximum:
        msg = f"{label} minimum must not exceed maximum"
        raise ValueError(msg)


def _validate_length_bounds(
    minimum: int,
    maximum: int | None,
    *,
    minimum_name: str,
    maximum_name: str,
    label: str,
) -> None:
    if minimum < 0:
        msg = f"{label} {minimum_name} must be non-negative"
        raise ValueError(msg)
    if maximum is not None and maximum < 0:
        msg = f"{label} {maximum_name} must be non-negative"
        raise ValueError(msg)
    if maximum is not None and minimum > maximum:
        msg = f"{label} {minimum_name} must not exceed {maximum_name}"
        raise ValueError(msg)


def _validate_id(value: str, *, label: str) -> None:
    if not value:
        msg = f"{label} id must be non-empty"
        raise ValueError(msg)


def _validate_unique_ids(values: Iterable[str], *, label: str) -> None:
    selected = tuple(values)
    duplicates = sorted({value for value in selected if selected.count(value) > 1})
    if duplicates:
        msg = f"{label} must be unique: {', '.join(duplicates)}"
        raise ValueError(msg)


__all__ = [
    "AtomType",
    "Bool",
    "Entity",
    "Float",
    "Int",
    "Payload",
    "Quantity",
    "Record",
    "RecordField",
    "Route",
    "Scalar",
    "Series",
    "String",
    "Table",
    "TableColumn",
    "ValueType",
]

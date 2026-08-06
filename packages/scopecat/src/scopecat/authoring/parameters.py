"""Typed handles for one-owner parameter table schemas."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Protocol, cast, overload

from scopecat.authoring.entity_selection import EachEntity, PerEntity
from scopecat.config.parameter_updates import (
    UpdateParameterRows,
    update_parameter_rows,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_types import (
    Bool,
    Entity,
    Float,
    Int,
    Scalar,
    String,
    Table,
    TableColumn,
)
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_validation import coerce_literal
from scopecat.program.value_refs import ValueRef
from scopecat.program.values import parameter, parameter_lookup
from scopecat.records.parameter import ParameterCatalog, ParameterDefinition

type ParameterScalar = Quantity | EntityRef | bool | int | float | str
type ParameterAtomType = Bool | Entity | Float | Int | QuantityType | String


class _ParameterFieldIdentity(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def value_type(self) -> Scalar: ...


@dataclass(frozen=True, slots=True)
class ParameterRowKey:
    """One closed primary-key field binding."""

    field: _ParameterFieldIdentity
    value: ParameterScalar


@dataclass(frozen=True, slots=True)
class ParameterAssignment:
    """One typed concrete table field assignment."""

    field: _ParameterFieldIdentity
    value: ParameterScalar


@dataclass(frozen=True, slots=True)
class ParameterField[T: ParameterScalar = ParameterScalar]:
    """Typed identity and scalar schema for one parameter table field."""

    id: str
    value_type: Scalar

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("parameter field id must be non-empty")

    @overload
    def key(
        self: ParameterField[Quantity],
        value: Quantity | float,
        /,
    ) -> ParameterRowKey: ...

    @overload
    def key(self, value: T, /) -> ParameterRowKey: ...

    def key(self, value: ParameterScalar, /) -> ParameterRowKey:
        """Bind this field as one closed row-key component."""

        return ParameterRowKey(self, _coerce_field_value(self, value))

    @overload
    def value(
        self: ParameterField[Quantity],
        value: Quantity | float,
        /,
    ) -> ParameterAssignment: ...

    @overload
    def value(self, value: T, /) -> ParameterAssignment: ...

    def value(self, value: ParameterScalar, /) -> ParameterAssignment:
        """Bind one concrete value for row creation or update."""

        return ParameterAssignment(self, _coerce_field_value(self, value))


type _AnyParameterField = (
    ParameterField[bool]
    | ParameterField[EntityRef | str]
    | ParameterField[float]
    | ParameterField[int]
    | ParameterField[Quantity]
    | ParameterField[str]
)


def _coerce_field_value(
    field: _ParameterFieldIdentity,
    value: ParameterScalar,
) -> ParameterScalar:
    return cast(
        "ParameterScalar",
        coerce_literal(
            field.value_type,
            value,
            path=("parameter", field.id),
        ),
    )


@overload
def parameter_field(id: str, value_type: Bool) -> ParameterField[bool]: ...


@overload
def parameter_field(
    id: str,
    value_type: Entity,
) -> ParameterField[EntityRef | str]: ...


@overload
def parameter_field(id: str, value_type: Float) -> ParameterField[float]: ...


@overload
def parameter_field(id: str, value_type: Int) -> ParameterField[int]: ...


@overload
def parameter_field(
    id: str,
    value_type: QuantityType,
) -> ParameterField[Quantity]: ...


@overload
def parameter_field(id: str, value_type: String) -> ParameterField[str]: ...


def parameter_field(
    id: str,
    value_type: ParameterAtomType,
) -> _AnyParameterField:
    """Declare one field while inferring its caller-facing Python type."""

    return cast(
        "_AnyParameterField", ParameterField(id=id, value_type=Scalar(value_type))
    )


@dataclass(frozen=True, slots=True)
class ParameterSchema:
    """One typed table parameter shared by authoring, catalog, and updates."""

    id: str
    fields: tuple[_ParameterFieldIdentity, ...]
    primary_key: tuple[_ParameterFieldIdentity, ...]
    description: str | None = None
    _ref: ValueRef[list[dict[str, object]]] = dataclass_field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("parameter schema id must be non-empty")
        if not self.fields:
            raise ValueError("parameter schema requires at least one field")
        field_ids = tuple(item.id for item in self.fields)
        if len(set(field_ids)) != len(field_ids):
            raise ValueError("parameter schema field ids must be unique")
        if not self.primary_key:
            raise ValueError("parameter schema requires a primary key")
        if len({item.id for item in self.primary_key}) != len(self.primary_key):
            raise ValueError("parameter schema primary key must be unique")
        fields_by_id = {item.id: item for item in self.fields}
        for item in self.primary_key:
            if fields_by_id.get(item.id) is not item:
                raise ValueError(
                    "parameter schema primary key fields must belong to its fields"
                )
        object.__setattr__(
            self,
            "_ref",
            parameter(self.id, self.value_type),
        )

    @property
    def value_type(self) -> Table:
        return Table(
            columns=tuple(
                TableColumn(item.id, item.value_type) for item in self.fields
            ),
            primary_key=tuple(item.id for item in self.primary_key),
        )

    @property
    def definition(self) -> ParameterDefinition:
        """Return the persisted catalog definition derived from this schema."""

        return ParameterDefinition(
            id=self.id,
            value_type=self.value_type,
            description=self.description,
        )

    @property
    def ref(self) -> ValueRef[list[dict[str, object]]]:
        """Return the stable compiler-only reference to the complete table."""

        return self._ref

    def row(self, *key: ParameterRowKey) -> ParameterRow:
        """Select one closed primary-key row."""

        selected = {item.field.id: item for item in key}
        expected = tuple(item.id for item in self.primary_key)
        if tuple(selected) != expected or len(selected) != len(key):
            raise ValueError(
                "parameter row key must match schema primary key in declaration order"
            )
        fields_by_id = {item.id: item for item in self.primary_key}
        for item in key:
            if fields_by_id.get(item.field.id) is not item.field:
                raise ValueError("parameter row key field belongs to another schema")
        return ParameterRow(self, tuple(key))

    def join(
        self,
        entities: EachEntity,
        *,
        on: ParameterField[EntityRef | str],
        where: tuple[ParameterRowKey, ...] = (),
    ) -> PerEntity[ParameterRow]:
        """Join concrete entities to rows through one entity primary-key field.

        ``where`` closes any other primary-key fields in declaration order.
        The returned rows retain entity identity through ``PerEntity``, so
        callers can project cells with ``map`` without positional alignment.
        """

        self.require_field_internal(on)
        expected = self.primary_key
        selected = (*where, on.key(entities.entities[0]))
        selected_fields = tuple(item.field for item in selected)
        selected_field_ids = tuple(id(field) for field in selected_fields)
        expected_field_ids = tuple(id(field) for field in expected)
        if len(set(selected_field_ids)) != len(expected_field_ids) or set(
            selected_field_ids
        ) != set(expected_field_ids):
            raise ValueError(
                "parameter join keys must close every primary-key field exactly once"
            )

        where_by_field_id = {id(item.field): item for item in where}
        return PerEntity(
            (
                entity,
                self.row(
                    *(
                        on.key(entity) if field is on else where_by_field_id[id(field)]
                        for field in expected
                    )
                ),
            )
            for entity in entities
        )

    def require_field_internal(self, selected: _ParameterFieldIdentity) -> None:
        if not any(item is selected for item in self.fields):
            raise ValueError("parameter field belongs to another schema")


def parameter_schema(
    id: str,
    *,
    fields: tuple[_ParameterFieldIdentity, ...],
    primary_key: tuple[_ParameterFieldIdentity, ...],
    description: str | None = None,
) -> ParameterSchema:
    """Declare one typed table parameter as the catalog source of truth."""

    return ParameterSchema(
        id=id,
        fields=fields,
        primary_key=primary_key,
        description=description,
    )


def parameter_catalog(id: str, *schemas: ParameterSchema) -> ParameterCatalog:
    """Build one persisted catalog from typed parameter schemas."""

    return ParameterCatalog(
        id=id,
        definitions=tuple(schema.definition for schema in schemas),
    )


@dataclass(frozen=True, slots=True)
class ParameterRow:
    """One closed table row that can be read symbolically or updated."""

    schema: ParameterSchema
    key: tuple[ParameterRowKey, ...]
    _cells: dict[int, object] = dataclass_field(
        default_factory=dict,
        init=False,
        repr=False,
        compare=False,
    )

    def __getitem__[T: ParameterScalar](
        self,
        selected: ParameterField[T],
    ) -> ParameterCell[T]:
        """Return the stable typed cell handle for one field."""

        self.schema.require_field_internal(selected)
        cache_key = id(selected)
        cached = self._cells.get(cache_key)
        if cached is not None:
            return cast("ParameterCell[T]", cached)
        created = ParameterCell(row=self, field=selected)
        self._cells[cache_key] = created
        return created

    def values(
        self,
        *assignments: ParameterAssignment,
    ) -> dict[str, ParameterScalar]:
        """Build one complete stored row without repeating its primary key."""

        selected = self._assignment_values(assignments, include_key=True)
        expected = {item.id for item in self.schema.fields}
        if set(selected) != expected:
            missing = ", ".join(sorted(expected - set(selected)))
            extra = ", ".join(sorted(set(selected) - expected))
            details = "; ".join(
                item
                for item in (
                    f"missing: {missing}" if missing else "",
                    f"extra: {extra}" if extra else "",
                )
                if item
            )
            raise ValueError(f"parameter row values must cover every field ({details})")
        return selected

    def update(
        self,
        *assignments: ParameterAssignment,
    ) -> UpdateParameterRows:
        """Build one typed update for non-key fields in this row."""

        if not assignments:
            raise ValueError("parameter row update requires at least one field")
        values = self._assignment_values(assignments, include_key=False)
        return update_parameter_rows(
            self.schema.id,
            key={item.field.id: item.value for item in self.key},
            values=values,
        )

    def _assignment_values(
        self,
        assignments: tuple[ParameterAssignment, ...],
        *,
        include_key: bool,
    ) -> dict[str, ParameterScalar]:
        selected: dict[str, ParameterScalar] = (
            {item.field.id: item.value for item in self.key} if include_key else {}
        )
        primary_key_ids = {item.field.id for item in self.key}
        for assignment in assignments:
            self.schema.require_field_internal(assignment.field)
            if assignment.field.id in primary_key_ids:
                raise ValueError("parameter row assignments cannot replace key fields")
            if assignment.field.id in selected:
                raise ValueError("parameter row assignments must be unique")
            selected[assignment.field.id] = assignment.value
        return selected


@dataclass(frozen=True, slots=True)
class ParameterCell[T: ParameterScalar = ParameterScalar]:
    """One typed scalar cell shared by lookup and configuration updates."""

    row: ParameterRow
    field: ParameterField[T]
    _ref: ValueRef[T] = dataclass_field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_ref",
            cast(
                "ValueRef[T]",
                parameter_lookup(
                    self.row.schema.id,
                    key={item.field.id: item.value for item in self.row.key},
                    column=self.field.id,
                    value_type=self.field.value_type,
                ),
            ),
        )

    @property
    def ref(self) -> ValueRef[T]:
        """Return this cell's stable symbolic lookup reference."""

        return self._ref

    @overload
    def update(
        self: ParameterCell[Quantity],
        value: Quantity | float,
        /,
    ) -> UpdateParameterRows: ...

    @overload
    def update(self, value: T, /) -> UpdateParameterRows: ...

    def update(self, value: ParameterScalar, /) -> UpdateParameterRows:
        """Build a concrete update for this cell."""

        return self.row.update(self.field.value(cast("T", value)))


__all__ = [
    "ParameterAssignment",
    "ParameterCell",
    "ParameterField",
    "ParameterRow",
    "ParameterRowKey",
    "ParameterScalar",
    "ParameterSchema",
    "parameter_catalog",
    "parameter_field",
    "parameter_schema",
]

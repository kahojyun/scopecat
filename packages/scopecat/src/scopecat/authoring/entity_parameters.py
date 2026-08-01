"""Entity-keyed parameter authoring with explicit cardinality.

This module makes single- and multi-entity parameter selection share one
authoring shape. ``one`` binds one row and ``each`` binds an identity-keyed
``PerEntity`` of rows; every row column remains one scalar lookup. It does not
promise or implement planner fanout for instrument operations.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import cast, overload, override

from scopecat.kernel.entity import EntityRef, entity_identity
from scopecat.kernel.value_type_compatibility import is_assignable
from scopecat.kernel.value_types import (
    Entity,
    Scalar,
    Table,
    TableColumn,
)
from scopecat.program.value_refs import ValueRef
from scopecat.program.values import parameter_lookup

type ConcreteEntityInput = EntityRef | str
type EntityInput = ConcreteEntityInput | ValueRef


class OneEntity:
    """An explicit single-entity selection.

    A symbolic entity ``ValueRef`` is accepted here because one lookup retains
    scalar cardinality and can be resolved for each experiment point.
    """

    __slots__ = ("_entity",)

    def __init__(self, entity: EntityInput, *, kind: str | None = None) -> None:
        self._entity = _select_one_entity(entity, kind=kind)

    @property
    def entity(self) -> EntityRef | ValueRef:
        return self._entity


class EachEntity:
    """An ordered, non-empty selection of distinct concrete entities.

    Exact matching uses durable entity identity ``(kind, id)`` and deliberately
    ignores descriptive metadata. Selected ids must also be globally distinct
    because topology and routing currently address entities by string id.
    Symbolic entities are not accepted because a ``PerEntity`` result must be
    keyed by known entity identity, never by positional zip semantics.
    """

    __slots__ = ("_entities",)

    def __init__(
        self,
        entities: Iterable[ConcreteEntityInput],
        *,
        kind: str | None = None,
    ) -> None:
        selected = tuple(
            _select_concrete_entity(entity, kind=kind) for entity in entities
        )
        if not selected:
            msg = "each() requires at least one entity"
            raise ValueError(msg)
        identities = tuple(entity_identity(entity) for entity in selected)
        duplicates = sorted(
            {identity for identity in identities if identities.count(identity) > 1},
            key=lambda identity: (identity[0] or "", identity[1]),
        )
        if duplicates:
            formatted = ", ".join(
                _format_entity_identity(value) for value in duplicates
            )
            msg = f"each() entities must have distinct identities: {formatted}"
            raise ValueError(msg)
        entity_ids = tuple(entity.id for entity in selected)
        duplicate_ids = sorted(
            {entity_id for entity_id in entity_ids if entity_ids.count(entity_id) > 1}
        )
        if duplicate_ids:
            formatted = ", ".join(duplicate_ids)
            msg = (
                "each() entity ids must be globally unique for topology and routing: "
                f"{formatted}"
            )
            raise ValueError(msg)
        self._entities = selected

    @property
    def entities(self) -> tuple[EntityRef, ...]:
        return self._entities

    def __iter__(self) -> Iterator[EntityRef]:
        return iter(self._entities)

    def __len__(self) -> int:
        return len(self._entities)

    def align[ValueT](
        self,
        value: ValueT | PerEntity[ValueT],
    ) -> PerEntity[ValueT]:
        """Broadcast one value or align an exact identity-keyed mapping."""

        if not isinstance(value, PerEntity):
            return PerEntity((entity, value) for entity in self)

        selected = cast("PerEntity[ValueT]", value)
        expected = {entity_identity(entity) for entity in self}
        actual = {entity_identity(entity) for entity in selected}
        if expected != actual:
            missing = sorted(
                expected - actual,
                key=lambda identity: (identity[0] or "", identity[1]),
            )
            extra = sorted(
                actual - expected,
                key=lambda identity: (identity[0] or "", identity[1]),
            )
            details: list[str] = []
            if missing:
                details.append(
                    "missing "
                    + ", ".join(
                        _format_entity_identity(identity) for identity in missing
                    )
                )
            if extra:
                details.append(
                    "extra "
                    + ", ".join(_format_entity_identity(identity) for identity in extra)
                )
            raise ValueError(
                "PerEntity value must exactly match selected entities: "
                + "; ".join(details)
            )
        return PerEntity((entity, selected[entity]) for entity in self)


type EntitySelection = OneEntity | EachEntity


def one(entity: EntityInput, *, kind: str | None = None) -> OneEntity:
    """Select exactly one concrete or symbolic entity."""

    return OneEntity(entity, kind=kind)


def each(
    *entities: ConcreteEntityInput,
    kind: str | None = None,
) -> EachEntity:
    """Select one or more concrete entities for identity-keyed mapping."""

    return EachEntity(entities, kind=kind)


class PerEntity[T](Mapping[EntityRef, T]):
    """An immutable mapping aligned by durable entity identity.

    Iteration preserves declaration order. Lookup ignores entity metadata and
    compares the complete ``(kind, id)`` identity; values are never aligned by
    list position.
    """

    __slots__ = ("_entities", "_index", "_values")

    def __init__(
        self,
        values: Mapping[EntityRef, T] | Iterable[tuple[EntityRef, T]],
    ) -> None:
        items: tuple[tuple[EntityRef, T], ...]
        if isinstance(values, Mapping):
            items = tuple(cast("Mapping[EntityRef, T]", values).items())
        else:
            items = tuple(values)
        entities = tuple(entity for entity, _value in items)
        identities = tuple(entity_identity(entity) for entity in entities)
        duplicates = sorted(
            {identity for identity in identities if identities.count(identity) > 1},
            key=lambda identity: (identity[0] or "", identity[1]),
        )
        if duplicates:
            formatted = ", ".join(
                _format_entity_identity(value) for value in duplicates
            )
            msg = f"PerEntity keys must have distinct identities: {formatted}"
            raise ValueError(msg)
        self._entities = entities
        self._values = tuple(value for _entity, value in items)
        self._index = {identity: index for index, identity in enumerate(identities)}

    @override
    def __getitem__(self, entity: EntityRef) -> T:
        try:
            index = self._index[entity_identity(entity)]
        except KeyError:
            raise KeyError(entity) from None
        return self._values[index]

    @override
    def __iter__(self) -> Iterator[EntityRef]:
        return iter(self._entities)

    @override
    def __len__(self) -> int:
        return len(self._entities)

    def map[ResultT](self, fn: Callable[[T], ResultT]) -> PerEntity[ResultT]:
        """Project values while preserving their entity identity keys."""

        return PerEntity((entity, fn(self[entity])) for entity in self)


class EntityKey:
    """The single entity primary key of a typed parameter table."""

    __slots__ = ("_id", "_value_type")

    def __init__(self, id: str, *, kind: str | None = None) -> None:
        if not id:
            msg = "parameter entity key id must be non-empty"
            raise ValueError(msg)
        self._id = id
        self._value_type = Scalar(Entity(entity_kind=kind))

    @property
    def id(self) -> str:
        return self._id

    @property
    def kind(self) -> str | None:
        return cast("Entity", self._value_type.atom).entity_kind

    @property
    def value_type(self) -> Scalar:
        return self._value_type


def entity_key(id: str, *, kind: str | None = None) -> EntityKey:
    """Declare an entity primary-key column once for a parameter table."""

    return EntityKey(id, kind=kind)


class ParameterColumn:
    """A typed parameter-table column and bound row descriptor."""

    __slots__ = ("_attribute_name", "_id", "_value_type")

    def __init__(self, value_type: Scalar, *, id: str | None = None) -> None:
        if id is not None and not id:
            msg = "parameter column id must be non-empty when provided"
            raise ValueError(msg)
        self._id = id
        self._value_type = value_type
        self._attribute_name: str | None = None

    def __set_name__(self, owner: type[object], name: str) -> None:
        del owner
        if self._attribute_name is not None and self._attribute_name != name:
            msg = "one parameter column descriptor cannot bind multiple attributes"
            raise TypeError(msg)
        self._attribute_name = name

    @property
    def id(self) -> str:
        selected = self._id or self._attribute_name
        if selected is None:
            msg = "parameter column must be attached to a ParameterRow subclass"
            raise TypeError(msg)
        return selected

    @property
    def value_type(self) -> Scalar:
        return self._value_type

    @overload
    def __get__(
        self,
        instance: None,
        owner: type[object] | None = None,
    ) -> ParameterColumn: ...

    @overload
    def __get__(
        self,
        instance: ParameterRow,
        owner: type[object] | None = None,
    ) -> ValueRef: ...

    def __get__(
        self,
        instance: ParameterRow | None,
        owner: type[object] | None = None,
    ) -> ParameterColumn | ValueRef:
        del owner
        if instance is None:
            return self
        return instance.__parameter_lookup__(self)

    def __set__(self, instance: object, value: object) -> None:
        del instance, value
        msg = "parameter columns are read-only"
        raise AttributeError(msg)


def parameter_column(
    value_type: Scalar,
    *,
    id: str | None = None,
) -> ParameterColumn:
    """Declare one result column on a ``ParameterRow`` schema."""

    return ParameterColumn(value_type, id=id)


class ParameterRow:
    """Base class for declarative parameter-row schemas.

    Subclasses declare named ``parameter_column`` descriptors. They are bound
    by ``ParameterTable.__getitem__`` and should not define an initializer.
    """

    __slots__ = ("_entity", "_table")

    def __init__(
        self,
        table: ParameterTable[ParameterRow],
        entity: EntityRef | ValueRef,
    ) -> None:
        self._table = table
        self._entity = entity

    def __parameter_lookup__(
        self,
        column: ParameterColumn,
    ) -> ValueRef:
        return self._table.__parameter_lookup__(self._entity, column)


class ParameterTable[RowT: ParameterRow]:
    """A typed entity-keyed parameter table bound to one row schema.

    ``TABLE[one(...)]`` returns one typed row and ``TABLE[each(...)]`` returns
    ``PerEntity[Row]``. Every row column is therefore always exactly one
    ``ValueRef``; callers can use ``PerEntity.map`` to project a column while
    retaining identity keys. Multi-entity parameter lookup and typed-client
    ``each(...)`` operations both expand explicitly by entity identity during
    authoring; neither asks a driver to broadcast one runtime command.
    """

    __slots__ = ("_columns", "_id", "_key", "_row_type", "_value_type")

    def __init__(
        self,
        id: str,
        *,
        key: EntityKey,
        row: type[RowT],
    ) -> None:
        if not id:
            msg = "parameter table id must be non-empty"
            raise ValueError(msg)
        columns = _row_columns(row)
        column_ids = tuple(column.id for column in columns)
        duplicates = sorted(
            {column_id for column_id in column_ids if column_ids.count(column_id) > 1}
        )
        if duplicates:
            msg = "parameter row column ids must be unique: " + ", ".join(duplicates)
            raise ValueError(msg)
        if key.id in column_ids:
            msg = f"parameter row column {key.id!r} conflicts with its entity key"
            raise ValueError(msg)
        self._id = id
        self._key = key
        self._row_type = row
        self._columns = columns
        self._value_type = Table(
            primary_key=(key.id,),
            columns=(
                TableColumn(id=key.id, value_type=key.value_type),
                *(
                    TableColumn(id=column.id, value_type=column.value_type)
                    for column in columns
                ),
            ),
        )

    @property
    def id(self) -> str:
        return self._id

    @property
    def key(self) -> EntityKey:
        return self._key

    @property
    def row_type(self) -> type[RowT]:
        return self._row_type

    @property
    def value_type(self) -> Table:
        """Return the reusable exact catalog schema for this table."""

        return self._value_type

    @overload
    def __getitem__(self, selection: OneEntity) -> RowT: ...

    @overload
    def __getitem__(self, selection: EachEntity) -> PerEntity[RowT]: ...

    def __getitem__(
        self,
        selection: EntitySelection,
    ) -> RowT | PerEntity[RowT]:
        if isinstance(selection, OneEntity):
            entity = _bind_entity_to_key(selection.entity, self._key)
            return self._bind_row(entity)
        bound_entities = tuple(
            _bind_concrete_entity_to_key(entity, self._key) for entity in selection
        )
        return PerEntity((entity, self._bind_row(entity)) for entity in bound_entities)

    def _bind_row(self, entity: EntityRef | ValueRef) -> RowT:
        row = self._row_type.__new__(self._row_type)
        ParameterRow.__init__(
            row,
            cast("ParameterTable[ParameterRow]", self),
            entity,
        )
        return row

    def __parameter_lookup__(
        self,
        entity: EntityRef | ValueRef,
        column: ParameterColumn,
    ) -> ValueRef:
        if column not in self._columns:
            msg = "parameter column does not belong to this table's row schema"
            raise ValueError(msg)
        return parameter_lookup(
            self._id,
            key={self._key.id: entity},
            column=column.id,
            value_type=column.value_type,
        )


def _row_columns(row_type: type[ParameterRow]) -> tuple[ParameterColumn, ...]:
    selected: dict[str, ParameterColumn] = {}
    shadowed: set[str] = set()
    for owner in row_type.__mro__:
        if owner is ParameterRow:
            break
        namespace = cast("Mapping[str, object]", owner.__dict__)
        for name, value in namespace.items():
            if name in shadowed:
                continue
            shadowed.add(name)
            if isinstance(value, ParameterColumn):
                selected[name] = value
    return tuple(selected.values())


def _select_one_entity(
    entity: EntityInput,
    *,
    kind: str | None,
) -> EntityRef | ValueRef:
    if isinstance(entity, ValueRef):
        _require_symbolic_entity(entity, kind=kind)
        return entity
    return _select_concrete_entity(entity, kind=kind)


def _select_concrete_entity(
    entity: ConcreteEntityInput,
    *,
    kind: str | None,
) -> EntityRef:
    if isinstance(entity, str):
        return EntityRef(id=entity, kind=kind)
    return _constrain_entity_kind(entity, kind=kind)


def _bind_entity_to_key(
    entity: EntityRef | ValueRef,
    key: EntityKey,
) -> EntityRef | ValueRef:
    if isinstance(entity, ValueRef):
        if not is_assignable(entity.value_type, key.value_type):
            msg = f"symbolic entity is incompatible with parameter key {key.id!r}"
            raise TypeError(msg)
        return entity
    return _bind_concrete_entity_to_key(entity, key)


def _bind_concrete_entity_to_key(entity: EntityRef, key: EntityKey) -> EntityRef:
    return _constrain_entity_kind(entity, kind=key.kind)


def _constrain_entity_kind(entity: EntityRef, *, kind: str | None) -> EntityRef:
    if kind is None or entity.kind == kind:
        return entity
    if entity.kind is not None:
        msg = f"entity {entity.id!r} has kind {entity.kind!r}, not {kind!r}"
        raise ValueError(msg)
    return entity.model_copy(update={"kind": kind})


def _require_symbolic_entity(entity: ValueRef, *, kind: str | None) -> None:
    value_type = entity.value_type
    if not isinstance(value_type, Scalar) or not isinstance(value_type.atom, Entity):
        msg = "one() symbolic selection requires an entity scalar ValueRef"
        raise TypeError(msg)
    if kind is not None and not is_assignable(
        value_type,
        Scalar(Entity(entity_kind=kind)),
    ):
        msg = f"symbolic entity is not constrained to kind {kind!r}"
        raise TypeError(msg)


def _format_entity_identity(identity: tuple[str | None, str]) -> str:
    kind, id = identity
    return f"{kind}:{id}" if kind is not None else id


__all__ = [
    "ConcreteEntityInput",
    "EachEntity",
    "EntityInput",
    "EntityKey",
    "EntitySelection",
    "OneEntity",
    "ParameterColumn",
    "ParameterRow",
    "ParameterTable",
    "PerEntity",
    "each",
    "entity_key",
    "one",
    "parameter_column",
]

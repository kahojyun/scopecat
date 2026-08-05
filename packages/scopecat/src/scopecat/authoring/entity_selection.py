"""Entity selection with explicit cardinality and identity-keyed values."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import cast, override

from scopecat.kernel.entity import EntityRef, entity_identity
from scopecat.kernel.value_type_compatibility import is_assignable
from scopecat.kernel.value_types import Entity, Scalar
from scopecat.program.value_refs import ValueRef

type ConcreteEntityInput = EntityRef | str
type EntityInput = ConcreteEntityInput | ValueRef


class OneEntity:
    """An explicit single-entity selection.

    A symbolic entity ``ValueRef`` is accepted because a single selection
    retains scalar cardinality and can be resolved for each experiment point.
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
    "EntitySelection",
    "OneEntity",
    "PerEntity",
    "each",
    "one",
]

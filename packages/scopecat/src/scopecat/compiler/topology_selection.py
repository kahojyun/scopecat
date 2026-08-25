"""Deterministic config-time resolution of retained topology selections."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from scopecat.kernel.entity import EntityRef
from scopecat.kernel.value_types import Entity, Table
from scopecat.program.table_values import (
    LiteralTableSource,
    TopologyConnectionSetSource,
    TopologyEntitySetSource,
    literal_table_source,
)
from scopecat.records.config import Topology


class TopologySelectionError(ValueError):
    """One entity-set intent cannot be satisfied by the accepted topology."""


@dataclass(frozen=True, slots=True)
class TopologyEntitySetResolution:
    """A retained selection intent and its config-specific ordered entities."""

    source: TopologyEntitySetSource
    entities: tuple[EntityRef, ...]
    table: LiteralTableSource


@dataclass(frozen=True, slots=True)
class TopologyConnectionSetResolution:
    """A retained edge selection and its config-specific relation table."""

    source: TopologyConnectionSetSource
    table: LiteralTableSource


type TopologyTableResolution = (
    TopologyEntitySetResolution | TopologyConnectionSetResolution
)


def resolve_topology_entity_set(
    topology: Topology,
    source: TopologyEntitySetSource,
    value_type: Table,
) -> TopologyEntitySetResolution:
    """Resolve one entity table in topology declaration order."""

    if len(value_type.columns) != 1:
        raise TopologySelectionError(
            "topology entity selections require a one-column entity table"
        )
    [column] = value_type.columns
    if not (
        isinstance(column.value_type.atom, Entity)
        and column.value_type.atom.entity_kind == source.entity_kind
    ):
        raise TopologySelectionError(
            "topology entity selection kind does not match its table column"
        )
    candidates = tuple(
        entity for entity in topology.entities if entity.kind == source.entity_kind
    )
    if not candidates:
        raise TopologySelectionError(
            f"topology has no entities of kind {source.entity_kind!r}"
        )
    if source.connected:
        selected = _connected_entities(topology, source, candidates)
    else:
        selected = candidates if source.count is None else candidates[: source.count]
    if source.count is not None and len(selected) < source.count:
        qualifier = "connected " if source.connected else ""
        raise TopologySelectionError(
            f"topology cannot provide {source.count} {qualifier}entities of kind "
            f"{source.entity_kind!r}; found {len(selected)}"
        )
    return TopologyEntitySetResolution(
        source=source,
        entities=selected,
        table=literal_table_source(tuple({column.id: entity} for entity in selected)),
    )


def _connected_entities(
    topology: Topology,
    source: TopologyEntitySetSource,
    candidates: tuple[EntityRef, ...],
) -> tuple[EntityRef, ...]:
    by_id = {entity.id: entity for entity in candidates}
    if source.anchor_id is not None and source.anchor_id not in by_id:
        raise TopologySelectionError(
            f"topology selection anchor {source.anchor_id!r} is not an entity of "
            f"kind {source.entity_kind!r}"
        )
    adjacency = {entity.id: set[str]() for entity in candidates}
    for connection in topology.connections:
        if (
            source.connection_kind is not None
            and connection.kind != source.connection_kind
        ):
            continue
        left, right = connection.endpoints
        if left in by_id and right in by_id:
            adjacency[left].add(right)
            adjacency[right].add(left)
    order = {entity.id: index for index, entity in enumerate(candidates)}
    start = source.anchor_id or candidates[0].id
    pending = deque((start,))
    visited: set[str] = set()
    selected: list[EntityRef] = []
    while pending and (source.count is None or len(selected) < source.count):
        entity_id = pending.popleft()
        if entity_id in visited:
            continue
        visited.add(entity_id)
        selected.append(by_id[entity_id])
        pending.extend(
            sorted(
                adjacency[entity_id] - visited,
                key=order.__getitem__,
            )
        )
    return tuple(selected)


def resolve_topology_connection_set(
    topology: Topology,
    source: TopologyConnectionSetSource,
    value_type: Table,
) -> TopologyConnectionSetResolution:
    """Resolve ordered qubit-pair rows, optionally selecting one matching."""

    expected_columns = ("left", "right", "coupler")
    if tuple(column.id for column in value_type.columns) != expected_columns:
        raise TopologySelectionError(
            "topology connection selections require left/right/coupler columns"
        )
    expected_kinds = (
        source.endpoint_entity_kind,
        source.endpoint_entity_kind,
        source.connection_entity_kind,
    )
    for column, expected_kind in zip(
        value_type.columns,
        expected_kinds,
        strict=True,
    ):
        atom = column.value_type.atom
        if not isinstance(atom, Entity) or atom.entity_kind != expected_kind:
            raise TopologySelectionError(
                f"topology connection column {column.id!r} must contain "
                f"{expected_kind!r} entities"
            )

    entities = {entity.id: entity for entity in topology.entities}
    selected = tuple(
        connection
        for connection in topology.connections
        if source.connection_kind is None or connection.kind == source.connection_kind
    )
    rows: list[dict[str, EntityRef]] = []
    edge_colors: list[int] = []
    colors_by_endpoint: dict[str, set[int]] = {}
    for connection in selected:
        left_id, right_id = connection.endpoints
        left = entities[left_id]
        right = entities[right_id]
        if (
            left.kind != source.endpoint_entity_kind
            or right.kind != source.endpoint_entity_kind
        ):
            continue
        if connection.entity_id is None:
            raise TopologySelectionError(
                f"topology connection {connection.id!r} has no associated entity"
            )
        connection_entity = entities[connection.entity_id]
        if connection_entity.kind != source.connection_entity_kind:
            raise TopologySelectionError(
                f"topology connection {connection.id!r} entity "
                f"{connection.entity_id!r} has kind {connection_entity.kind!r}, "
                f"not {source.connection_entity_kind!r}"
            )
        unavailable = colors_by_endpoint.get(left_id, set()) | colors_by_endpoint.get(
            right_id,
            set(),
        )
        color = next(
            index for index in range(len(selected) + 1) if index not in unavailable
        )
        colors_by_endpoint.setdefault(left_id, set()).add(color)
        colors_by_endpoint.setdefault(right_id, set()).add(color)
        edge_colors.append(color)
        rows.append({"left": left, "right": right, "coupler": connection_entity})

    if not rows:
        raise TopologySelectionError("topology connection selection is empty")
    if source.matching is not None:
        rows = [
            row
            for row, color in zip(rows, edge_colors, strict=True)
            if color == source.matching
        ]
        if not rows:
            raise TopologySelectionError(
                f"topology has no matching layer {source.matching} "
                "for the selected connections"
            )
    return TopologyConnectionSetResolution(
        source=source,
        table=literal_table_source(rows),
    )


__all__ = [
    "TopologyConnectionSetResolution",
    "TopologyEntitySetResolution",
    "TopologySelectionError",
    "TopologyTableResolution",
    "resolve_topology_connection_set",
    "resolve_topology_entity_set",
]

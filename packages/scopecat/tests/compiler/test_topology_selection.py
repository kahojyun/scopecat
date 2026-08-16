from __future__ import annotations

import pytest
from pydantic import ValidationError

from scopecat.compiler.topology_selection import (
    TopologySelectionError,
    resolve_topology_entity_set,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.value_types import Entity, Scalar, Table, TableColumn
from scopecat.program.table_values import TopologyEntitySetSource
from scopecat.records.config import Topology, TopologyConnection


def _qubit_table() -> Table:
    return Table(
        columns=(
            TableColumn(
                "qubit",
                Scalar(Entity(entity_kind="logical_qubit")),
            ),
        ),
        primary_key=("qubit",),
    )


def _topology() -> Topology:
    return Topology(
        entities=[
            EntityRef(id="q0", kind="logical_qubit"),
            EntityRef(id="q1", kind="logical_qubit"),
            EntityRef(id="q2", kind="logical_qubit"),
            EntityRef(id="q3", kind="logical_qubit"),
            EntityRef(id="q4", kind="logical_qubit"),
        ],
        connections=[
            TopologyConnection(
                id="q0-q1",
                kind="nearest_neighbor",
                endpoints=("q0", "q1"),
            ),
            TopologyConnection(
                id="q1-q2",
                kind="nearest_neighbor",
                endpoints=("q1", "q2"),
            ),
            TopologyConnection(
                id="q2-q3",
                kind="nearest_neighbor",
                endpoints=("q2", "q3"),
            ),
            TopologyConnection(
                id="q1-q4-bus",
                kind="shared_bus",
                endpoints=("q1", "q4"),
            ),
        ],
    )


def test_topology_selection_resolves_a_stable_connected_region() -> None:
    source = TopologyEntitySetSource(
        entity_kind="logical_qubit",
        count=3,
        connected=True,
        anchor_id="q1",
        connection_kind="nearest_neighbor",
    )
    resolution = resolve_topology_entity_set(
        _topology(),
        source,
        _qubit_table(),
    )

    assert [entity.id for entity in resolution.entities] == ["q1", "q0", "q2"]
    assert [row["qubit"] for row in resolution.table.rows] == list(resolution.entities)

    base = _topology()
    expanded = Topology(
        entities=[
            *base.entities,
            EntityRef(id="q5", kind="logical_qubit"),
        ],
        connections=[
            *base.connections,
            TopologyConnection(
                id="q3-q5",
                kind="nearest_neighbor",
                endpoints=("q3", "q5"),
            ),
        ],
    )
    expanded_resolution = resolve_topology_entity_set(
        expanded,
        source,
        _qubit_table(),
    )
    assert expanded_resolution.entities == resolution.entities


def test_topology_selection_reports_an_unsatisfied_connected_count() -> None:
    with pytest.raises(TopologySelectionError, match=r"5 connected.*found 4"):
        resolve_topology_entity_set(
            _topology(),
            TopologyEntitySetSource(
                entity_kind="logical_qubit",
                count=5,
                connected=True,
                anchor_id="q1",
                connection_kind="nearest_neighbor",
            ),
            _qubit_table(),
        )


def test_topology_rejects_connections_to_unknown_entities() -> None:
    with pytest.raises(ValidationError, match=r"unknown entities.*missing"):
        Topology(
            entities=[EntityRef(id="q0", kind="logical_qubit")],
            connections=[
                TopologyConnection(
                    id="broken",
                    kind="nearest_neighbor",
                    endpoints=("q0", "missing"),
                )
            ],
        )

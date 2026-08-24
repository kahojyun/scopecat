from __future__ import annotations

import pytest
from pydantic import ValidationError

from scopecat.compiler.topology_selection import (
    TopologySelectionError,
    resolve_topology_connection_set,
    resolve_topology_entity_set,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.value_types import Entity, Scalar, Table, TableColumn
from scopecat.program.table_values import (
    TopologyConnectionSetSource,
    TopologyEntitySetSource,
)
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


def _qubit_pair_table() -> Table:
    return Table(
        columns=(
            TableColumn(
                "left",
                Scalar(Entity(entity_kind="logical_qubit")),
            ),
            TableColumn(
                "right",
                Scalar(Entity(entity_kind="logical_qubit")),
            ),
            TableColumn(
                "coupler",
                Scalar(Entity(entity_kind="coupler")),
            ),
        ),
        primary_key=("coupler",),
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


def test_topology_connection_selection_resolves_stable_matching_layers() -> None:
    topology = Topology(
        entities=[
            *(EntityRef(id=f"q{index}", kind="logical_qubit") for index in range(4)),
            *(EntityRef(id=f"c{index}", kind="coupler") for index in range(3)),
        ],
        connections=[
            TopologyConnection(
                id=f"q{index}-q{index + 1}",
                kind="nearest_neighbor",
                endpoints=(f"q{index}", f"q{index + 1}"),
                entity_id=f"c{index}",
            )
            for index in range(3)
        ],
    )

    all_pairs = resolve_topology_connection_set(
        topology,
        TopologyConnectionSetSource(
            endpoint_entity_kind="logical_qubit",
            connection_entity_kind="coupler",
            connection_kind="nearest_neighbor",
        ),
        _qubit_pair_table(),
    )
    assert [row["coupler"].id for row in all_pairs.table.rows] == ["c0", "c1", "c2"]

    first_matching = resolve_topology_connection_set(
        topology,
        TopologyConnectionSetSource(
            endpoint_entity_kind="logical_qubit",
            connection_entity_kind="coupler",
            connection_kind="nearest_neighbor",
            matching=0,
        ),
        _qubit_pair_table(),
    )
    assert [row["coupler"].id for row in first_matching.table.rows] == ["c0", "c2"]

    second_matching = resolve_topology_connection_set(
        topology,
        TopologyConnectionSetSource(
            endpoint_entity_kind="logical_qubit",
            connection_entity_kind="coupler",
            connection_kind="nearest_neighbor",
            matching=1,
        ),
        _qubit_pair_table(),
    )
    assert [row["coupler"].id for row in second_matching.table.rows] == ["c1"]


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


def test_topology_rejects_connections_with_unknown_associated_entities() -> None:
    with pytest.raises(ValidationError, match=r"unknown entities.*missing-coupler"):
        Topology(
            entities=[
                EntityRef(id="q0", kind="logical_qubit"),
                EntityRef(id="q1", kind="logical_qubit"),
            ],
            connections=[
                TopologyConnection(
                    id="broken",
                    kind="nearest_neighbor",
                    endpoints=("q0", "q1"),
                    entity_id="missing-coupler",
                )
            ],
        )

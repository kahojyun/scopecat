"""Topology-bound selection intents for reusable quantum program calls."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.kernel.entity import EntityRef
from scopecat.program.table_values import (
    TopologyConnectionSetSource,
    TopologyEntitySetSource,
)
from scopecat.program.value_refs import ValueRef, internal_table_value_ref
from scopecat.program.value_types import Table

_LOGICAL_QUBIT_KIND = "logical_qubit"
_LOGICAL_COUPLER_KIND = "logical_coupler"


@dataclass(frozen=True, slots=True)
class QubitSelectionIntent:
    """Select logical qubits from the accepted configuration at bind time."""

    count: int | None = None
    connected: bool = False
    anchor_id: str | None = None
    connection_kind: str | None = None

    def __post_init__(self) -> None:
        self.topology_source()

    def topology_source(self) -> TopologyEntitySetSource:
        """Project the generic config-bound table source for this intent."""

        return TopologyEntitySetSource(
            entity_kind=_LOGICAL_QUBIT_KIND,
            count=self.count,
            connected=self.connected,
            anchor_id=self.anchor_id,
            connection_kind=self.connection_kind,
        )


def select_qubits(
    count: int | None = None,
    *,
    connected: bool = False,
    anchor: EntityRef | str | None = None,
    connection_kind: str | None = None,
) -> QubitSelectionIntent:
    """Retain a deterministic topology-backed qubit-set selection.

    Without ``connected``, selection follows topology entity declaration order.
    Connected selection uses breadth-first order, beginning at ``anchor`` or the
    first logical qubit. Omitting ``count`` selects all candidates or the entire
    selected connected component.
    """

    anchor_id: str | None
    if isinstance(anchor, EntityRef):
        if anchor.kind not in (None, _LOGICAL_QUBIT_KIND):
            raise ValueError(
                f"qubit selection anchor {anchor.id!r} has kind {anchor.kind!r}"
            )
        anchor_id = anchor.id
    else:
        anchor_id = anchor
    return QubitSelectionIntent(
        count=count,
        connected=connected,
        anchor_id=anchor_id,
        connection_kind=connection_kind,
    )


@dataclass(frozen=True, slots=True)
class CouplerSelectionIntent:
    """Select logical coupler entities from accepted topology order."""

    count: int | None = None

    def topology_source(self) -> TopologyEntitySetSource:
        return TopologyEntitySetSource(
            entity_kind=_LOGICAL_COUPLER_KIND,
            count=self.count,
        )


def select_couplers(count: int | None = None) -> CouplerSelectionIntent:
    """Select all or the first ``count`` logical couplers."""

    return CouplerSelectionIntent(count=count)


@dataclass(frozen=True, slots=True)
class QubitPairSelectionIntent:
    """Select topology edges, optionally restricted to one matching layer."""

    connection_kind: str | None = None
    matching: int | None = None

    def topology_source(self) -> TopologyConnectionSetSource:
        return TopologyConnectionSetSource(
            endpoint_entity_kind=_LOGICAL_QUBIT_KIND,
            connection_entity_kind=_LOGICAL_COUPLER_KIND,
            connection_kind=self.connection_kind,
            matching=self.matching,
        )


def select_qubit_pairs(
    *,
    connection_kind: str | None = None,
    matching: int | None = None,
) -> QubitPairSelectionIntent:
    """Select ordered qubit-pair rows from topology connection declarations."""

    return QubitPairSelectionIntent(
        connection_kind=connection_kind,
        matching=matching,
    )


def qubit_selection_value_ref(
    selection: QubitSelectionIntent,
    value_type: Table,
) -> ValueRef:
    return internal_table_value_ref(
        selection.topology_source(),
        value_type,
    )


def coupler_selection_value_ref(
    selection: CouplerSelectionIntent,
    value_type: Table,
) -> ValueRef:
    return internal_table_value_ref(selection.topology_source(), value_type)


def qubit_pair_selection_value_ref(
    selection: QubitPairSelectionIntent,
    value_type: Table,
) -> ValueRef:
    return internal_table_value_ref(selection.topology_source(), value_type)


__all__ = [
    "CouplerSelectionIntent",
    "QubitPairSelectionIntent",
    "QubitSelectionIntent",
    "select_couplers",
    "select_qubit_pairs",
    "select_qubits",
]

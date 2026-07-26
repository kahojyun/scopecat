from __future__ import annotations

import pytest

from scopecat.compiler.entity_resolution import (
    EntityResolutionError,
    resolve_entities,
    resolve_entity,
)
from scopecat.records.config import Topology
from scopecat.records.entity import EntityRef


def _topology() -> Topology:
    return Topology(
        entities=[
            EntityRef(
                id="q0",
                kind="logical_device",
                metadata={"source": "topology", "shared": "topology"},
            ),
            EntityRef(id="untyped", metadata={"source": "topology"}),
        ],
    )


def test_resolve_entity_completes_kind_and_merges_metadata() -> None:
    resolved = resolve_entity(
        _topology(),
        EntityRef(id="q0", metadata={"shared": "request", "label": "control"}),
    )

    assert resolved == EntityRef(
        id="q0",
        kind="logical_device",
        metadata={
            "source": "topology",
            "shared": "request",
            "label": "control",
        },
    )


def test_resolve_entity_retains_requested_kind_when_topology_has_none() -> None:
    assert resolve_entity(
        _topology(),
        EntityRef(id="untyped", kind="request_kind"),
    ) == EntityRef(
        id="untyped",
        kind="request_kind",
        metadata={"source": "topology"},
    )


def test_resolve_entities_preserves_order() -> None:
    assert resolve_entities(_topology(), ("untyped", "q0")) == (
        EntityRef(id="untyped", metadata={"source": "topology"}),
        EntityRef(
            id="q0",
            kind="logical_device",
            metadata={"source": "topology", "shared": "topology"},
        ),
    )


def test_resolve_entity_reports_structured_unknown_issue() -> None:
    with pytest.raises(EntityResolutionError) as caught:
        resolve_entity(
            _topology(),
            EntityRef(id="missing", kind="requested"),
        )

    issue = caught.value.issue
    assert issue.code == "unknown_entity"
    assert issue.entity_id == "missing"
    assert issue.actual_kind is None
    assert issue.requested_kind == "requested"


def test_resolve_entity_reports_structured_kind_mismatch() -> None:
    with pytest.raises(EntityResolutionError) as caught:
        resolve_entity(
            _topology(),
            EntityRef(id="q0", kind="logical_coupler"),
        )

    issue = caught.value.issue
    assert issue.code == "kind_mismatch"
    assert issue.entity_id == "q0"
    assert issue.actual_kind == "logical_device"
    assert issue.requested_kind == "logical_coupler"

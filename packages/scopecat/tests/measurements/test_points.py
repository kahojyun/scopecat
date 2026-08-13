from __future__ import annotations

from typing import cast

import pytest

from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.points import (
    AcceptedRunPoint,
    PointProposalAttempt,
)
from scopecat.kernel.quantity import Quantity


def _logical_id(ordinal: int) -> LogicalPointId:
    return LogicalPointId(PointDomainId("program", "accepted"), ordinal)


def test_point_proposal_has_stable_coordinate_and_attempt_identities() -> None:
    coordinates = {"frequency": Quantity(5.0, "GHz")}

    authored = PointProposalAttempt(coordinates)
    optimized = PointProposalAttempt(
        coordinates,
        source="optimizer",
        region_id="region-0",
        domain_proposal_fingerprint="sha256:domain",
        based_on_region_revision=4,
    )

    assert authored.coordinate_fingerprint == optimized.coordinate_fingerprint
    assert authored.proposal_fingerprint != optimized.proposal_fingerprint
    with pytest.raises(TypeError):
        cast("dict[str, object]", authored.coordinates)["frequency"] = Quantity(
            6.0, "GHz"
        )


def test_normalized_point_identity_includes_region_freshness() -> None:
    coordinates = {"frequency": Quantity(5.0, "GHz")}
    first = PointProposalAttempt(
        coordinates,
        source="operator",
        region_id="region-0",
        domain_proposal_fingerprint="sha256:domain",
        based_on_region_revision=2,
    )
    second = PointProposalAttempt(
        coordinates,
        source="operator",
        region_id="region-0",
        domain_proposal_fingerprint="sha256:domain",
        based_on_region_revision=3,
    )

    assert first.coordinate_fingerprint == second.coordinate_fingerprint
    assert first.proposal_fingerprint != second.proposal_fingerprint


def test_accepting_the_same_proposal_allocates_distinct_run_identity() -> None:
    proposal = PointProposalAttempt(
        {"frequency": Quantity(5.0, "GHz")},
        source="optimizer",
    )

    first = AcceptedRunPoint.accept(proposal, logical_id=_logical_id(0))
    second = AcceptedRunPoint.accept(proposal, logical_id=_logical_id(1))

    assert first.logical_id != second.logical_id
    assert first.proposal_fingerprint == second.proposal_fingerprint
    assert first.coordinates == second.coordinates
    assert first.source == second.source == "optimizer"

from __future__ import annotations

from typing import cast

import pytest

from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.points import (
    AcceptedRunPoint,
    OperatorPointRequest,
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
        based_on_completed_point_count=4,
    )

    assert authored.coordinate_fingerprint == optimized.coordinate_fingerprint
    assert authored.proposal_fingerprint != optimized.proposal_fingerprint
    with pytest.raises(TypeError):
        cast("dict[str, object]", authored.coordinates)["frequency"] = Quantity(
            6.0, "GHz"
        )


def test_operator_request_identity_is_independent_of_boundary_freshness() -> None:
    request = OperatorPointRequest(
        request_id="operator-1",
        coordinate_mode="free",
        requested_coordinates={"frequency": Quantity(5.0, "GHz")},
        coordinates={"frequency": Quantity(5.0, "GHz")},
    )
    first = PointProposalAttempt(
        request.coordinates,
        source="operator",
        based_on_completed_point_count=2,
    )
    second = PointProposalAttempt(
        request.coordinates,
        source="operator",
        based_on_completed_point_count=3,
    )

    assert request.coordinate_fingerprint == first.coordinate_fingerprint
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

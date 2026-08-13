from __future__ import annotations

from typing import cast

import pytest

from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.quantity import Quantity
from scopecat.measurements.points import AcceptedRunPoint, PointCandidate


def _logical_id(ordinal: int) -> LogicalPointId:
    return LogicalPointId(PointDomainId("program", "accepted"), ordinal)


def test_point_candidate_has_stable_coordinate_and_proposal_identities() -> None:
    coordinates = {"frequency": Quantity(5.0, "GHz")}

    authored = PointCandidate(coordinates)
    optimized = PointCandidate(
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


def test_accepting_the_same_candidate_allocates_distinct_run_identity() -> None:
    candidate = PointCandidate(
        {"frequency": Quantity(5.0, "GHz")},
        source="optimizer",
    )

    first = AcceptedRunPoint.accept(candidate, logical_id=_logical_id(0))
    second = AcceptedRunPoint.accept(candidate, logical_id=_logical_id(1))

    assert first.logical_id != second.logical_id
    assert first.proposal_fingerprint == second.proposal_fingerprint
    assert first.coordinates == second.coordinates
    assert first.source == second.source == "optimizer"

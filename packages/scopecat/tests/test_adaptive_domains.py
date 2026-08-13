from __future__ import annotations

from scopecat.adaptive_domains import (
    AdaptiveRegion,
    DomainProposalAttempt,
    ResolvedDomainAxis,
    ResolvedDomainFragment,
    ResolvedRangeSource,
)
from scopecat.kernel.quantity import Quantity


def test_grid_fragment_expands_lazily_in_declaration_order() -> None:
    fragment = ResolvedDomainFragment.grid(
        ResolvedDomainAxis.values_axis("frequency", (1, 2)),
        ResolvedDomainAxis.values_axis("power", (-10, 0)),
    )

    assert fragment.point_count == 4
    assert tuple(fragment.rows()) == (
        {"frequency": 1, "power": -10},
        {"frequency": 1, "power": 0},
        {"frequency": 2, "power": -10},
        {"frequency": 2, "power": 0},
    )


def test_point_fragment_is_a_one_row_domain() -> None:
    fragment = ResolvedDomainFragment.points(({"frequency": 5.0},))

    assert fragment.layout == "point_cloud"
    assert fragment.point_count == 1
    assert tuple(fragment.rows()) == ({"frequency": 5.0},)


def test_range_and_around_axes_resolve_concrete_quantity_values() -> None:
    ranged = ResolvedDomainAxis.range_axis(
        "frequency",
        Quantity(4, "GHz"),
        Quantity(6_000, "MHz"),
        points=3,
    )
    around = ResolvedDomainAxis.around_axis(
        "frequency",
        Quantity(5, "GHz"),
        Quantity(2_000, "MHz"),
        points=3,
    )

    expected = (
        Quantity(4, "GHz"),
        Quantity(5, "GHz"),
        Quantity(6, "GHz"),
    )
    assert ranged.values == expected
    assert around.values == expected
    assert isinstance(ranged.source, ResolvedRangeSource)


def test_domain_proposal_identity_includes_regions_and_freshness() -> None:
    fragment = ResolvedDomainFragment.points(({"frequency": 5.0},))
    first = DomainProposalAttempt(
        fragment,
        region_ids=("region-0",),
        based_on_region_revisions={"region-0": 2},
    )
    second = DomainProposalAttempt(
        fragment,
        region_ids=("region-1",),
        based_on_region_revisions={"region-1": 2},
    )

    assert first.proposal_fingerprint != second.proposal_fingerprint


def test_region_exposes_independent_budget_and_revision() -> None:
    region = AdaptiveRegion(
        id="region-0",
        coordinates={"temperature": 20.0},
        point_count=3,
        completed_point_count=2,
        revision=2,
        point_limit=8,
    )

    assert region.remaining_point_count == 5

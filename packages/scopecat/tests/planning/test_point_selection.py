from __future__ import annotations

import pytest

from scopecat.control.models import PointCoordinateSpec
from scopecat.kernel.quantity import Quantity
from scopecat.planning.point_selection import resolve_point_selection


def test_free_selection_uses_admissibility_not_authored_sampling_bounds() -> None:
    spec = PointCoordinateSpec(
        id="bias",
        kind="float",
        sampled_values=(0.0, 1.0),
    )

    resolved = resolve_point_selection((spec,), {"bias": 2.5}, mode="free")

    assert resolved.coordinates == {"bias": 2.5}
    with pytest.raises(ValueError, match="at most"):
        resolve_point_selection(
            (spec.model_copy(update={"maximum": 2.0}),),
            {"bias": 2.5},
            mode="free",
        )


def test_snap_selection_resolves_one_authored_point_row() -> None:
    specs = (
        PointCoordinateSpec(id="x", kind="float", sampled_values=(0.0, 1.0)),
        PointCoordinateSpec(
            id="duration",
            kind="quantity",
            unit="ns",
            sampled_values=(Quantity(10.0, "ns"), Quantity(30.0, "ns")),
        ),
    )
    points = (
        {"x": 0.0, "duration": Quantity(30.0, "ns")},
        {"x": 1.0, "duration": Quantity(10.0, "ns")},
    )

    resolved = resolve_point_selection(
        specs,
        {"x": 0.8, "duration": Quantity(12.0, "ns")},
        mode="snap",
        sampled_points=points,
    )

    assert resolved.sampled_point_index == 1
    assert resolved.coordinates == points[1]


def test_exact_and_snap_refuse_a_truncated_sampling_contract() -> None:
    spec = PointCoordinateSpec(id="x", kind="int", sampled_values=(1, 2))

    for mode in ("exact", "snap"):
        with pytest.raises(ValueError, match="complete authored point sampling"):
            resolve_point_selection(
                (spec,),
                {"x": 1},
                mode=mode,
                sampled_points=({"x": 1},),
                sampled_points_truncated=True,
            )

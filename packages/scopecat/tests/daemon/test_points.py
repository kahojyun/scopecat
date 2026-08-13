from __future__ import annotations

from scopecat.daemon.points import (
    RunDomainAxisView,
    RunDomainFragmentInput,
    RunDomainResolveCommand,
    RunDomainValuesSourceView,
)
from scopecat.kernel.quantity import Quantity


def test_operator_domain_input_does_not_require_server_derived_identity() -> None:
    command = RunDomainResolveCommand(
        coordinate_mode="free",
        region_scope="current",
        fragment=RunDomainFragmentInput(
            layout="grid",
            axes=(
                RunDomainAxisView(
                    axis_id="frequency",
                    source=RunDomainValuesSourceView(values=(Quantity(5.15, "GHz"),)),
                ),
            ),
        ),
    )

    encoded = command.model_dump(mode="json")["fragment"]

    assert "point_count" not in encoded
    assert "fragment_fingerprint" not in encoded

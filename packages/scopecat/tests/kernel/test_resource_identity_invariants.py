from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.frontend.graph_validation import verify_assembly_graph
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import ProblemPhase


def test_capability_less_authored_port_rejects_state_and_acquire_at_assembly() -> None:
    module = (
        sc.module_body(id="test.resource-identity.capability-less")
        .resource("drive")
        .bind_field(
            "drive",
            capability="set.frequency",
            field="value",
            value=1.0,
        )
        .product(
            "signal",
        )
        .acquire(
            "read-signal",
            "signal",
            resource="drive",
            capability="measure.signal",
        )
        .build()
    )

    with pytest.raises(CheckFailed) as caught:
        verify_assembly_graph(elaborate_module(module.ir))

    assert [problem.code for problem in caught.value.problems] == [
        "module_resource_port_capability_missing",
        "module_resource_port_capability_missing",
    ]
    assert all(
        problem.phase is ProblemPhase.AUTHORING for problem in caught.value.problems
    )

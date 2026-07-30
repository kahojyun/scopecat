from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.frontend.graph_validation import verify_assembly_graph
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import ProblemPhase
from scopecat.sdk.instruments import InterfaceRef

_SET_FREQUENCY_VALUE = InterfaceRef("test.set_frequency/v1").property("value")
_MEASURE_SIGNAL_VALUE = (
    InterfaceRef("test.measure_signal/v1").acquisition("sample").result("signal")
)


def test_interface_less_authored_port_rejects_state_and_acquire_at_assembly() -> None:
    module = (
        sc.procedure(id="test.resource-identity.interface-less")
        .resource("drive")
        .bind_property(
            "drive",
            _SET_FREQUENCY_VALUE,
            value=1.0,
        )
        .product(
            "signal",
        )
        .acquire(
            "read-signal",
            resource="drive",
            results={_MEASURE_SIGNAL_VALUE: "signal"},
        )
        .build()
    )

    with pytest.raises(CheckFailed) as caught:
        verify_assembly_graph(elaborate_module(module.ir))

    assert [problem.code for problem in caught.value.problems] == [
        "module_resource_port_interface_missing",
        "module_resource_port_interface_missing",
    ]
    assert all(
        problem.phase is ProblemPhase.AUTHORING for problem in caught.value.problems
    )

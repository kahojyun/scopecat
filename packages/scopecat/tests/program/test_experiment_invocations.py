from __future__ import annotations

from scopecat.kernel.value_types import Int, Scalar
from scopecat.program.definitions import (
    ExperimentDef,
    ExperimentInputDef,
    ExperimentInvocation,
)
from scopecat.program.module import ModuleBody, ModuleInterface


def test_bind_is_last_write_and_unbind_reinherits_definition_input() -> None:
    definition = ExperimentDef(
        id="test.invocation-inputs",
        kind="test",
        interface=ModuleInterface(),
        body=ModuleBody(),
        inputs=(ExperimentInputDef("shots", Scalar(Int()), default=2),),
    )

    selected = ExperimentInvocation(definition).bind(shots=3).bind(shots=5)
    inherited = selected.unbind("shots")

    assert selected.input_overrides == {"shots": 5}
    assert inherited.input_overrides == {}
    assert definition.inputs[0].default == 2

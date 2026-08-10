from __future__ import annotations

from typing import cast

import pytest

import scopecat as sc
from scopecat.compiler.frontend.resolution import compile_invocation


def test_registered_compute_has_a_resolvable_stable_implementation() -> None:
    registry = sc.ComputeRegistry()

    @registry.implementation(
        "window.peak",
        "2",
        input_codecs={"value": "scopecat.float64.v1"},
        capabilities=("numpy",),
        resources={"memory_mb": 64},
    )
    def peak(*, value: float) -> float:
        return value

    @sc.experiment
    def experiment(context: sc.ExperimentContext) -> sc.ValueRef[float]:
        return cast(
            "sc.ValueRef[float]",
            context.compute(
                fn=peak,
                inputs={"value": 1.5},
                output_type=sc.ScalarType(sc.FloatType()),
            ),
        )

    invocation = experiment()
    logical = compile_invocation(invocation).program.program
    [implementation] = logical.implementations.values()

    assert implementation.id.value == "registry:window.peak@2"
    assert implementation.deterministic
    assert registry.resolve("registry:window.peak@2") is peak
    contract = registry.contract("registry:window.peak@2")
    assert contract.deterministic
    assert contract.capabilities == ("numpy",)
    assert contract.resources == {"memory_mb": 64}

    with pytest.raises(KeyError, match="is not registered"):
        registry.resolve("registry:missing@1")

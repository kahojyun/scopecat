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


def test_custom_compute_output_codec_requires_an_encoder() -> None:
    registry = sc.ComputeRegistry()

    with pytest.raises(ValueError, match="require an encode_output"):
        registry.implementation(
            "test.missing-encoder",
            "1",
            output_codec="test.custom.v1",
        )


def test_registered_compute_declares_named_result_paths() -> None:
    registry = sc.ComputeRegistry()

    @registry.implementation(
        "test.fit",
        "1",
        outputs={
            "score": "score",
            "first_residual": ("residuals", 0),
        },
    )
    def fit(*, value: float) -> dict[str, object]:
        return {"score": value, "residuals": [value - 1]}

    contract = registry.contract("registry:test.fit@1")

    assert contract.outputs == {
        "score": ("score",),
        "first_residual": ("residuals", 0),
    }
    assert registry.resolve("registry:test.fit@1") is fit


def test_structured_compute_outputs_reject_one_root_encoder() -> None:
    registry = sc.ComputeRegistry()

    def encode(result: dict[str, float]) -> dict[str, float]:
        return {"score": result["score"]}

    with pytest.raises(ValueError, match="cannot use one root output encoder"):
        registry.implementation(
            "test.encoded-fit",
            "1",
            outputs={"score": "score"},
            encode_output=encode,
        )


def test_structured_compute_outputs_require_unique_paths() -> None:
    registry = sc.ComputeRegistry()

    with pytest.raises(ValueError, match="paths must be unique"):
        registry.implementation(
            "test.duplicate-output",
            "1",
            outputs={"first": "score", "second": "score"},
        )


def test_registered_compute_rejects_hidden_nonlocal_inputs() -> None:
    registry = sc.ComputeRegistry()
    scale = 2.0

    def captured(*, value: float) -> float:
        return value * scale

    with pytest.raises(ValueError, match="cannot capture nonlocal values: scale"):
        registry.implementation("test.captured", "1")(captured)

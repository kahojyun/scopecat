from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import scopecat as sc
from scopecat.kernel.errors import CheckFailed
from scopecat.measurements.results import MeasurementValue
from scopecat.sdk.instruments import InterfaceRef
from tests.testkit.authoring import bind_invocation, load_config

_SCALAR_SIGNAL = InterfaceRef("test.scalar_signal/v1")
_SCALAR_SIGNAL_SAMPLE_RAW = _SCALAR_SIGNAL.acquisition("sample").result("raw")


def _kernel(value: MeasurementValue) -> dict[str, MeasurementValue]:
    return {"result": value}


@dataclass(frozen=True, slots=True)
class _DerivedProducts:
    left: sc.ProductRef
    right: sc.ProductRef


def test_record_demand_retains_source_use_and_prunes_dead_postprocessor(
    tmp_path: Path,
) -> None:
    @sc.module(id="test.postprocessor.lowering")
    def module(context: sc.ModuleContext) -> sc.ProductRef:
        source = context._resource("source", requires=(_SCALAR_SIGNAL,))
        raw = context._product("raw")
        first = context._product("first")
        second = context._product("second")
        derived = context._product("derived")
        dead = context._product("dead")
        context._postprocess(
            "final",
            input=second,
            outputs={"result": derived},
            kernel=_kernel,
        )
        context._postprocess(
            "dead",
            input=raw,
            outputs={"result": dead},
            kernel=_kernel,
        )
        context._postprocess(
            "middle",
            input=first,
            outputs={"result": second},
            kernel=_kernel,
        )
        context._postprocess(
            "first",
            input=raw,
            outputs={"result": first},
            kernel=_kernel,
        )
        context._acquire(
            "read-raw",
            resource=source,
            results={_SCALAR_SIGNAL_SAMPLE_RAW: raw},
        )
        return derived

    @sc.experiment(id="test.postprocessor.lowering", kind="postprocessor")
    def template(experiment: sc.ExperimentContext) -> None:
        result = experiment.use(module())
        experiment.record(result, record_id="first")
        experiment.record(result, record_id="second")

    resolved = bind_invocation(template(), config_profile=load_config())
    program = resolved.bindings

    first, middle, final = program.measurement_postprocessors
    assert [
        postprocessor.id.qualified_name
        for postprocessor in program.measurement_postprocessors
    ] == ["lowering/first", "lowering/middle", "lowering/final"]
    assert first.input_product_id.qualified_name == "lowering/raw"
    assert first.outputs[0].product_use_ids == (middle.input_product_use_id,)
    assert middle.input_product_id.qualified_name == "lowering/first"
    assert middle.outputs[0].product_use_ids == (final.input_product_use_id,)
    assert final.input_product_id.qualified_name == "lowering/second"
    assert final.outputs[0].product_use_ids == tuple(
        record.product_use_id for record in program.product_record_uses
    )
    assert {use.product_id.qualified_name for use in program.product_uses} == {
        "lowering/raw",
        "lowering/first",
        "lowering/second",
        "lowering/derived",
    }
    assert {
        result.product_id.qualified_name
        for acquisition in resolved.program.program.acquisitions
        for result in acquisition.results
    } == {"lowering/raw"}
    assert all(
        postprocessor.kernel is _kernel
        for postprocessor in program.measurement_postprocessors
    )


def test_hidden_input_use_ids_are_stable_and_scoped(tmp_path: Path) -> None:
    @sc.module(id="test.postprocessor.hidden-id.child")
    def child(context: sc.ModuleContext) -> sc.ProductRef:
        source = context._resource("source", requires=(_SCALAR_SIGNAL,))
        raw = context._product("raw")
        derived = context._product("derived")
        context._postprocess(
            "derive",
            input=raw,
            outputs={"result": derived},
            kernel=_kernel,
        )
        context._acquire(
            "read-raw",
            resource=source,
            results={_SCALAR_SIGNAL_SAMPLE_RAW: raw},
        )
        return derived

    left = child.instantiate("left")
    right = child.instantiate("right")

    @sc.module(id="test.postprocessor.hidden-id.root")
    def root(context: sc.ModuleContext) -> _DerivedProducts:
        context.use(left)
        context.use(right)
        return _DerivedProducts(left=left.result, right=right.result)

    @sc.experiment(id="test.postprocessor.hidden-id", kind="postprocessor")
    def template(experiment: sc.ExperimentContext) -> None:
        result = experiment.use(root())
        experiment.record(result.left, record_id="left")
        experiment.record(result.right, record_id="right")

    def compile_input_use_ids() -> dict[str, str]:
        program = bind_invocation(
            template(),
            config_profile=load_config(),
        ).bindings
        return {
            postprocessor.id.qualified_name: (postprocessor.input_product_use_id.value)
            for postprocessor in program.measurement_postprocessors
        }

    assert (
        compile_input_use_ids()
        == compile_input_use_ids()
        == {
            "root/left/derive": (
                "scopecat.measurement-postprocessor/root/left/derive/input"
            ),
            "root/right/derive": (
                "scopecat.measurement-postprocessor/root/right/derive/input"
            ),
        }
    )


def test_recorded_product_requires_a_producer() -> None:
    @sc.module(id="test.product.owner")
    def module(context: sc.ModuleContext) -> sc.ProductRef:
        return context._product("orphan")

    @sc.experiment(id="test.product.owner", kind="product-owner")
    def template(experiment: sc.ExperimentContext) -> None:
        result = experiment.use(module())
        experiment.record(result)

    with pytest.raises(CheckFailed) as error:
        bind_invocation(template(), config_profile=load_config())

    assert [problem.code for problem in error.value.problems] == [
        "product_acquire_missing"
    ]

from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.kernel.errors import CheckFailed
from scopecat.measurements.results import MeasurementValue
from scopecat.program.measurements import (
    MeasurementPostprocessor,
    measurement_postprocessor,
)
from scopecat.sdk.instruments import InterfaceRef
from tests.testkit.authoring import bind_invocation, load_config

_SCALAR_SIGNAL = InterfaceRef("test.scalar_signal/v1")
_SCALAR_SIGNAL_SAMPLE_RAW = _SCALAR_SIGNAL.acquisition("sample").result("raw")


def _kernel(value: MeasurementValue) -> dict[str, MeasurementValue]:
    return {"result": value}


def _postprocessor(
    id: str,
    *,
    source: str,
    output: str,
) -> MeasurementPostprocessor:
    return measurement_postprocessor(
        id,
        input=source,
        outputs={"result": output},
        kernel=_kernel,
    )


def test_record_demand_retains_source_use_and_prunes_dead_postprocessor(
    tmp_path: Path,
) -> None:
    @sc.module(id="test.postprocessor.lowering")
    def module(context: sc.ModuleContext) -> None:
        source = context._resource("source", requires=(_SCALAR_SIGNAL,))
        raw = context.product("raw")
        context.product("derived")
        context.product("dead")
        context.measurement_postprocessor(
            _postprocessor("dead", source="raw", output="dead")
        )
        context.measurement_postprocessor(
            _postprocessor("derive", source="raw", output="derived")
        )
        context._acquire(
            "read-raw",
            resource=source,
            results={_SCALAR_SIGNAL_SAMPLE_RAW: raw},
        )

    @sc.template(id="test.postprocessor.lowering", kind="postprocessor")
    def template(experiment: sc.ExperimentContext) -> None:
        call = experiment.run(module())
        experiment.record(call.products.derived, record_id="first")
        experiment.record(call.products.derived, record_id="second")

    resolved = bind_invocation(template(), config_profile=load_config())
    program = resolved.bindings

    [postprocessor] = program.measurement_postprocessors
    assert postprocessor.id.qualified_name == "lowering/derive"
    assert postprocessor.input_product_id.qualified_name == "lowering/raw"
    assert postprocessor.input_product_use_id.value == (
        "scopecat.measurement-postprocessor/lowering/derive/input"
    )
    assert postprocessor.outputs[0].product_use_ids == tuple(
        record.product_use_id for record in program.record_uses
    )
    assert {use.product_id.qualified_name for use in program.product_uses} == {
        "lowering/raw",
        "lowering/derived",
    }
    assert {
        result.product_id.qualified_name
        for acquisition in resolved.program.program.acquisitions
        for result in acquisition.results
    } == {"lowering/raw"}
    assert postprocessor.kernel is _kernel


def test_hidden_input_use_ids_are_stable_and_scoped(tmp_path: Path) -> None:
    @sc.module(id="test.postprocessor.hidden-id.child")
    def child(context: sc.ModuleContext) -> None:
        source = context._resource("source", requires=(_SCALAR_SIGNAL,))
        raw = context.product("raw")
        context.product("derived")
        context.measurement_postprocessor(
            _postprocessor("derive", source="raw", output="derived")
        )
        context._acquire(
            "read-raw",
            resource=source,
            results={_SCALAR_SIGNAL_SAMPLE_RAW: raw},
        )

    left = child.instantiate("left")
    right = child.instantiate("right")

    @sc.module(id="test.postprocessor.hidden-id.root")
    def root(context: sc.ModuleContext) -> None:
        context.call(left)
        context.call(right)

    @sc.template(id="test.postprocessor.hidden-id", kind="postprocessor")
    def template(experiment: sc.ExperimentContext) -> None:
        call = experiment.run(root())
        experiment.record(call.products["left/derived"], record_id="left")
        experiment.record(call.products["right/derived"], record_id="right")

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
    def module(context: sc.ModuleContext) -> None:
        context.product("orphan")

    @sc.template(id="test.product.owner", kind="product-owner")
    def template(experiment: sc.ExperimentContext) -> None:
        call = experiment.run(module())
        experiment.record(call.products.orphan)

    with pytest.raises(CheckFailed) as error:
        bind_invocation(template(), config_profile=load_config())

    assert [problem.code for problem in error.value.problems] == [
        "product_acquire_missing"
    ]

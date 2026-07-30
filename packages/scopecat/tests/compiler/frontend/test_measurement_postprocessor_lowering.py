from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.compiler.typed.program import core_acquisitions
from scopecat.kernel.errors import CheckFailed
from scopecat.measurements.results import MeasurementValue
from scopecat.sdk.instruments import InterfaceRef
from tests.testkit.authoring import link_invocation, load_config, template_fixture
from tests.testkit.typed_program import link_program

_SCALAR_SIGNAL = InterfaceRef("test.scalar_signal/v1")
_SCALAR_SIGNAL_SAMPLE_RAW = _SCALAR_SIGNAL.acquisition("sample").result("raw")


def _kernel(value: MeasurementValue) -> dict[str, MeasurementValue]:
    return {"result": value}


def _postprocessor(
    id: str,
    *,
    source: str,
    output: str,
) -> sc.MeasurementPostprocessor:
    return sc.measurement_postprocessor(
        id,
        input=source,
        outputs={"result": output},
        kernel=_kernel,
    )


def test_record_demand_retains_source_use_and_prunes_dead_postprocessor(
    tmp_path: Path,
) -> None:
    module = (
        sc.procedure(id="test.postprocessor.lowering")
        .resource("source", requires=(_SCALAR_SIGNAL,))
        .product("raw", "derived", "dead")
        .measurement_postprocessors(
            _postprocessor("dead", source="raw", output="dead"),
            _postprocessor("derive", source="raw", output="derived"),
        )
        .acquire(
            "read-raw",
            resource="source",
            results={_SCALAR_SIGNAL_SAMPLE_RAW: "raw"},
        )
        .build()
    )
    template = template_fixture(
        module,
        id="test.postprocessor.lowering",
        kind="postprocessor",
        records=(
            sc.record_product(module.products.derived, record_id="first"),
            sc.record_product(module.products.derived, record_id="second"),
        ),
    )

    resolved = link_invocation(template.bind(), config_profile=load_config())
    program = resolved.program

    [postprocessor] = program.measurement_postprocessors
    assert postprocessor.id.qualified_name == "derive"
    assert postprocessor.input_product_id.qualified_name == "raw"
    assert postprocessor.input_product_use_id.value == (
        "scopecat.measurement-postprocessor/derive/input"
    )
    assert postprocessor.outputs[0].product_use_ids == tuple(
        record.product_use_id for record in program.record_uses
    )
    assert {use.product_id.qualified_name for use in program.product_uses} == {
        "raw",
        "derived",
    }
    assert {
        result.product_id.qualified_name
        for acquisition in core_acquisitions(program)
        for result in acquisition.results
    } == {"raw"}
    assert postprocessor.kernel is _kernel

    linked = link_program(program, resolved.environment)
    assert linked.program.measurement_postprocessors == (postprocessor,)


def test_hidden_input_use_ids_are_stable_and_scoped(tmp_path: Path) -> None:
    child = (
        sc.procedure(id="test.postprocessor.hidden-id.child")
        .resource("source", requires=(_SCALAR_SIGNAL,))
        .product("raw", "derived")
        .measurement_postprocessors(
            _postprocessor("derive", source="raw", output="derived")
        )
        .acquire(
            "read-raw",
            resource="source",
            results={_SCALAR_SIGNAL_SAMPLE_RAW: "raw"},
        )
        .build()
    )
    left = child.instantiate("left")
    right = child.instantiate("right")
    root = sc.procedure(id="test.postprocessor.hidden-id.root").use(left, right).build()
    template = template_fixture(
        root,
        id="test.postprocessor.hidden-id",
        kind="postprocessor",
        records=(
            sc.record_product(left.products.derived, record_id="left"),
            sc.record_product(right.products.derived, record_id="right"),
        ),
    )

    def compile_input_use_ids() -> dict[str, str]:
        program = link_invocation(
            template.bind(),
            config_profile=load_config(),
        ).program
        return {
            postprocessor.id.qualified_name: (postprocessor.input_product_use_id.value)
            for postprocessor in program.measurement_postprocessors
        }

    assert (
        compile_input_use_ids()
        == compile_input_use_ids()
        == {
            "left/derive": "scopecat.measurement-postprocessor/left/derive/input",
            "right/derive": "scopecat.measurement-postprocessor/right/derive/input",
        }
    )


def test_recorded_product_requires_a_producer() -> None:
    module = sc.procedure(id="test.product.owner").product("orphan").build()
    template = template_fixture(
        module,
        id="test.product.owner",
        kind="product-owner",
        records=(sc.record_product(module.products.orphan),),
    )

    with pytest.raises(CheckFailed) as error:
        link_invocation(template.bind(), config_profile=load_config())

    assert [problem.code for problem in error.value.problems] == [
        "product_acquire_missing"
    ]

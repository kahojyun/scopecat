# pyright: reportUnusedFunction=false

from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.compiler.frontend.elaboration import compose_module
from scopecat.compiler.frontend.logical_verification import verify_logical_program
from scopecat.kernel.errors import CheckFailed
from scopecat.measurements.results import MeasurementValue
from scopecat.program.domain import domain_program
from tests.testkit.domain import domain_call


def _identity(value: MeasurementValue) -> dict[str, MeasurementValue]:
    return {"result": value}


def _postprocessor(
    id: str,
    *,
    source: str | sc.ProductRef,
    output: str | sc.ProductRef,
) -> sc.MeasurementPostprocessor:
    return sc.measurement_postprocessor(
        id,
        input=source,
        outputs={"result": output},
        kernel=_identity,
    )


def test_measurement_postprocessor_captures_one_input_outputs_and_kernel() -> None:
    postprocessor = sc.measurement_postprocessor(
        "derive",
        input="raw",
        outputs={"first": "a", "second": "b"},
        kernel=_identity,
    )

    assert postprocessor.input_binding.qualified_name == "raw"
    assert tuple(
        (role, product_id.qualified_name)
        for role, product_id in postprocessor.output_bindings
    ) == (("first", "a"), ("second", "b"))
    assert postprocessor.kernel is _identity


def test_measurement_postprocessor_validates_authoring_ingress() -> None:
    with pytest.raises(ValueError, match="input product id"):
        sc.measurement_postprocessor(
            "derive",
            input="",
            outputs={"result": "derived"},
            kernel=_identity,
        )
    with pytest.raises(ValueError, match="at least one output"):
        sc.measurement_postprocessor(
            "derive",
            input="raw",
            outputs={},
            kernel=_identity,
        )
    with pytest.raises(ValueError, match="input and outputs must be distinct"):
        sc.measurement_postprocessor(
            "derive",
            input="raw",
            outputs={"result": "raw"},
            kernel=_identity,
        )


def test_module_requires_postprocessor_products_and_unique_ids() -> None:
    postprocessor = _postprocessor("derive", source="raw", output="derived")

    with pytest.raises(ValueError, match="undeclared local product 'raw'"):

        @sc.module(id="test.postprocessor.missing")
        def missing(context: sc.ModuleContext) -> None:
            context.product("derived")
            context.measurement_postprocessor(postprocessor)

    with pytest.raises(
        ValueError,
        match="duplicate module measurement postprocessor ids",
    ):

        @sc.module(id="test.postprocessor.duplicate")
        def duplicate(context: sc.ModuleContext) -> None:
            context.product("raw")
            context.product("derived")
            context.measurement_postprocessor(postprocessor)
            context.measurement_postprocessor(postprocessor)


def test_postprocessor_reads_child_product_and_is_hygienically_scoped() -> None:
    @sc.module(id="test.postprocessor.source")
    def child(context: sc.ModuleContext) -> None:
        context.product("raw")

    nested = child.instantiate("nested")

    @sc.module(id="test.postprocessor.parent")
    def module(context: sc.ModuleContext) -> None:
        context.call(nested)
        derived = context.product("derived")
        context.measurement_postprocessor(
            sc.measurement_postprocessor(
                "derive",
                input=nested.products.raw,
                outputs={"result": derived},
                kernel=_identity,
            )
        )

    [lowered] = compose_module(module.ir).measurement_postprocessors
    assert lowered.input.qualified_name == "nested/raw"
    assert lowered.outputs[0][1].qualified_name == "derived"

    @sc.module(id="test.postprocessor.child")
    def nested_module(context: sc.ModuleContext) -> None:
        context.product("raw")
        context.product("derived")
        context.measurement_postprocessor(
            _postprocessor("derive", source="raw", output="derived")
        )

    @sc.module(id="test.postprocessor.root")
    def root(context: sc.ModuleContext) -> None:
        context.call(nested_module.instantiate("nested"))

    [scoped] = compose_module(root.ir).measurement_postprocessors
    assert scoped.id.qualified_name == "nested/derive"
    assert scoped.input.qualified_name == "nested/raw"


def test_postprocessor_chaining_is_rejected() -> None:
    @sc.module(id="test.postprocessor.chain")
    def module(context: sc.ModuleContext) -> None:
        context.product("raw")
        context.product("middle")
        context.product("derived")
        context.measurement_postprocessor(
            _postprocessor("first", source="raw", output="middle"),
        )
        context.measurement_postprocessor(
            _postprocessor("second", source="middle", output="derived"),
        )

    with pytest.raises(CheckFailed) as error:
        verify_logical_program(compose_module(module.ir))
    assert {problem.code for problem in error.value.problems} == {
        "semantic_measurement_postprocessor_chaining_unsupported"
    }


def test_domain_and_postprocessor_cannot_own_the_same_product() -> None:
    program = domain_program(
        "program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        results={"raw": None},
    )

    @sc.module(id="test.postprocessor.owner")
    def module(context: sc.ModuleContext) -> None:
        call = domain_call(program)
        context.product("source")
        context.measurement_postprocessor(
            _postprocessor("derive", source="source", output=call.results.raw)
        )
        context.call(call)

    with pytest.raises(CheckFailed) as error:
        verify_logical_program(compose_module(module.ir))
    assert "semantic_product_producer_duplicate" in {
        problem.code for problem in error.value.problems
    }

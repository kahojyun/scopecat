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


def test_module_requires_postprocessor_products_and_unique_ids() -> None:
    foreign = sc.ModuleContext()._product("raw")

    with pytest.raises(ValueError, match="outside this module"):

        @sc.module(id="test.postprocessor.missing")
        def missing(context: sc.ModuleContext) -> None:
            derived = context._product("derived")
            context._postprocess(
                "derive",
                input=foreign,
                outputs={"result": derived},
                kernel=_identity,
            )

    with pytest.raises(
        ValueError,
        match="duplicate module measurement postprocessor ids",
    ):

        @sc.module(id="test.postprocessor.duplicate")
        def duplicate(context: sc.ModuleContext) -> None:
            raw = context._product("raw")
            derived = context._product("derived")
            context._postprocess(
                "derive",
                input=raw,
                outputs={"result": derived},
                kernel=_identity,
            )
            context._postprocess(
                "derive",
                input=raw,
                outputs={"result": derived},
                kernel=_identity,
            )


def test_postprocessor_reads_child_product_and_is_hygienically_scoped() -> None:
    @sc.module(id="test.postprocessor.source")
    def child(context: sc.ModuleContext) -> None:
        context._product("raw")

    nested = child.instantiate("nested")

    @sc.module(id="test.postprocessor.parent")
    def module(context: sc.ModuleContext) -> None:
        context.call(nested)
        derived = context._product("derived")
        context._postprocess(
            "derive",
            input=nested.products.raw,
            outputs={"result": derived},
            kernel=_identity,
        )

    [lowered] = compose_module(module.definition).measurement_postprocessors
    assert lowered.input.qualified_name == "nested/raw"
    assert lowered.outputs[0][1].qualified_name == "derived"

    @sc.module(id="test.postprocessor.child")
    def nested_module(context: sc.ModuleContext) -> None:
        raw = context._product("raw")
        derived = context._product("derived")
        context._postprocess(
            "derive",
            input=raw,
            outputs={"result": derived},
            kernel=_identity,
        )

    @sc.module(id="test.postprocessor.root")
    def root(context: sc.ModuleContext) -> None:
        context.call(nested_module.instantiate("nested"))

    [scoped] = compose_module(root.definition).measurement_postprocessors
    assert scoped.id.qualified_name == "nested/derive"
    assert scoped.input.qualified_name == "nested/raw"


def test_postprocessor_chaining_is_rejected() -> None:
    @sc.module(id="test.postprocessor.chain")
    def module(context: sc.ModuleContext) -> None:
        raw = context._product("raw")
        middle = context._product("middle")
        derived = context._product("derived")
        context._postprocess(
            "first",
            input=raw,
            outputs={"result": middle},
            kernel=_identity,
        )
        context._postprocess(
            "second",
            input=middle,
            outputs={"result": derived},
            kernel=_identity,
        )

    with pytest.raises(CheckFailed) as error:
        verify_logical_program(compose_module(module.definition))
    assert {problem.code for problem in error.value.problems} == {
        "logical_measurement_postprocessor_chaining_unsupported"
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
        source = context._product("source")
        context._postprocess(
            "derive",
            input=source,
            outputs={"result": call.results.raw},
            kernel=_identity,
        )
        context.call(call)

    with pytest.raises(CheckFailed) as error:
        verify_logical_program(compose_module(module.definition))
    assert "logical_product_producer_duplicate" in {
        problem.code for problem in error.value.problems
    }

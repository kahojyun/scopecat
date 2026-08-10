# pyright: reportUnusedFunction=false

from __future__ import annotations

import numpy as np
import pytest

import scopecat as sc
from scopecat.compiler.frontend.elaboration import compose_module
from scopecat.compiler.frontend.logical_verification import verify_logical_program
from scopecat.kernel.errors import CheckFailed
from scopecat.measurements.results import (
    MeasurementArray,
    MeasurementScalar,
    MeasurementValue,
)
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
    def child(context: sc.ModuleContext) -> sc.ProductRef:
        return context._product("raw")

    nested = child.instantiate("nested")

    @sc.module(id="test.postprocessor.parent")
    def module(context: sc.ModuleContext) -> None:
        context.use(nested)
        derived = context._product("derived")
        context._postprocess(
            "derive",
            input=nested.result,
            outputs={"result": derived},
            kernel=_identity,
        )

    [lowered] = compose_module(module.definition).measurement_postprocessors
    assert lowered.inputs[0][1].qualified_name == "nested/raw"
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
        context.use(nested_module.instantiate("nested"))

    [scoped] = compose_module(root.definition).measurement_postprocessors
    assert scoped.id.qualified_name == "nested/derive"
    assert scoped.inputs[0][1].qualified_name == "nested/raw"


def test_compute_lowers_multiple_measured_inputs_to_the_observation_stage() -> None:
    @sc.module(id="test.measurement-compute")
    def module(context: sc.ModuleContext) -> sc.ProductRef:
        left = context._product("left", unit="V")
        right = context._product("right", unit="V")
        return context.compute(
            "pair",
            fn=lambda *, left, right: np.asarray([left, right]),
            inputs={"left": left, "right": right},
            output_type=sc.ArrayType(
                dtype="float64",
                dimensions=(sc.ArrayDimension("channel", 2),),
                unit="V",
            ),
        )

    logical = compose_module(module.definition)

    [compute] = logical.measurement_postprocessors
    assert [(name, product.qualified_name) for name, product in compute.inputs] == [
        ("left", "left"),
        ("right", "right"),
    ]
    output = compute.kernel(
        {
            "left": MeasurementScalar.create(
                value=1.0,
                dtype="float64",
                unit="V",
            ),
            "right": MeasurementScalar.create(
                value=2.0,
                dtype="float64",
                unit="V",
            ),
        }
    )["result"]
    assert isinstance(output, MeasurementArray)
    assert output.values.tolist() == [1.0, 2.0]
    assert output.unit == "V"


def test_compute_joins_measured_products_with_earlier_compute_values() -> None:
    @sc.module(id="test.mixed-availability-compute")
    def module(context: sc.ModuleContext) -> sc.ProductRef:
        threshold = context.compute(
            "threshold",
            fn=lambda *, base: base * 2.0,
            inputs={"base": 1.5},
            output_type=sc.ScalarType(sc.FloatType()),
        )
        signal = context._product("signal", unit="V")
        return context.compute(
            "classify",
            fn=lambda *, signal, threshold: signal > threshold,
            inputs={"signal": signal, "threshold": threshold},
            output_type=sc.ScalarType(sc.BoolType()),
        )

    logical = compose_module(module.definition)

    [threshold] = logical.compute_nodes
    [classify] = logical.measurement_postprocessors
    assert classify.value_inputs == (("threshold", threshold.result_id),)
    result = classify.kernel(
        {
            "signal": MeasurementScalar.create(
                value=4.0,
                dtype="float64",
                unit="V",
            ),
            "threshold": 3.0,
        }
    )["result"]
    assert result == MeasurementScalar.create(value=True, dtype="bool")


def test_postprocessor_chaining_is_sorted_by_dependency() -> None:
    @sc.module(id="test.postprocessor.chain")
    def module(context: sc.ModuleContext) -> None:
        raw = context._product("raw")
        middle = context._product("middle")
        derived = context._product("derived")
        context._postprocess(
            "second",
            input=middle,
            outputs={"result": derived},
            kernel=_identity,
        )
        context._postprocess(
            "first",
            input=raw,
            outputs={"result": middle},
            kernel=_identity,
        )

    verified = verify_logical_program(compose_module(module.definition))

    assert [
        postprocessor.id.qualified_name
        for postprocessor in verified.program.measurement_postprocessors
    ] == ["first", "second"]


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
        context.use(call)

    with pytest.raises(CheckFailed) as error:
        verify_logical_program(compose_module(module.definition))
    assert "logical_product_producer_duplicate" in {
        problem.code for problem in error.value.problems
    }

from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat.compiler.typed.program import core_acquisitions
from scopecat.planning.authoring import resolve_experiment
from tests.testkit.authoring import load_config
from tests.testkit.typed_program import link_program


def _semantic(name: str) -> sc.MeasurementTransformSemanticContract:
    return sc.MeasurementTransformSemanticContract(
        id=name,
        version="1",
    )


def _transform(
    id: str,  # noqa: A002
    *,
    source: str,
    output: str,
) -> sc.MeasurementTransform:
    return sc.measurement_transform(
        id,
        semantic=_semantic(f"test.{id}"),
        inputs={"source": source},
        outputs={"result": output},
    )


def test_record_demand_closes_transform_inputs_and_prunes_dead_transform(
    tmp_path: Path,
) -> None:
    module = (
        sc.module("test.transform.lowering")
        .resource("source", requires=("scalar_signal",))
        .product("raw", "middle", "derived", "dead")
        .measurement_transforms(
            _transform("dead-transform", source="raw", output="dead"),
            _transform("second", source="middle", output="derived"),
            _transform("first", source="raw", output="middle"),
        )
        .acquire(
            "read-raw",
            "raw",
            resource="source",
            capability="scalar_signal",
        )
        .build()
    )
    template = (
        module.template("test.transform.lowering", kind="transform")
        .record_product(module.products.derived, record_id="first-result")
        .record_product(module.products.derived, record_id="second-result")
        .build()
    )

    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )
    program = resolved.experiment

    assert tuple(
        transform.id.qualified_name for transform in program.measurement_transforms
    ) == ("first", "second")
    first, second = program.measurement_transforms
    assert first.inputs[0].product_id.qualified_name == "raw"
    assert second.inputs[0].product_id.qualified_name == "middle"
    assert first.outputs[0].product_use_ids == (second.inputs[0].product_use_id,)
    assert second.outputs[0].product_use_ids == tuple(
        record.product_use_id for record in program.record_uses
    )
    assert {use.product_id.qualified_name for use in program.product_uses} == {
        "raw",
        "middle",
        "derived",
    }
    assert {
        product.product_id.qualified_name
        for acquisition in core_acquisitions(program)
        for product in acquisition.products
    } == {"raw"}
    assert {
        output.product_id.qualified_name
        for transform in program.measurement_transforms
        for output in transform.outputs
    } == {"middle", "derived"}
    assert all(
        product.product_id.qualified_name != "dead"
        for product in (
            *(
                product
                for acquisition in core_acquisitions(program)
                for product in acquisition.products
            ),
            *(
                output
                for transform in program.measurement_transforms
                for output in transform.outputs
            ),
        )
    )

    linked = link_program(program, resolved.environment)
    assert linked.measurement_transforms == program.measurement_transforms


def test_hidden_transform_input_use_ids_are_stable_scoped_and_escaped(
    tmp_path: Path,
) -> None:
    child = (
        sc.module("test.transform.hidden-id.child")
        .resource("source", requires=("scalar_signal",))
        .product("raw", "derived")
        .measurement_transforms(
            sc.measurement_transform(
                "derive/%",
                semantic=_semantic("test.hidden-id"),
                inputs={"source/%": "raw"},
                outputs={"result": "derived"},
            )
        )
        .acquire(
            "read-raw",
            "raw",
            resource="source",
            capability="scalar_signal",
        )
        .build()
    )
    left = child.instantiate("left")
    right = child.instantiate("right")
    root = sc.module("test.transform.hidden-id.root").use(left, right).build()
    template = (
        root.template("test.transform.hidden-id", kind="transform")
        .record_product(left.products.derived, record_id="left")
        .record_product(right.products.derived, record_id="right")
        .build()
    )

    def compile_input_use_ids() -> dict[str, str]:
        resolved = resolve_experiment(
            template.bind(),
            config_profile=load_config(),
        )
        return {
            transform.id.qualified_name: transform.inputs[0].product_use_id.value
            for transform in resolved.experiment.measurement_transforms
        }

    first = compile_input_use_ids()
    second = compile_input_use_ids()

    assert first == second
    assert first == {
        "left/derive%2F%25": (
            "scopecat.measurement-transform/left/derive%2F%25/inputs/source%2F%25"
        ),
        "right/derive%2F%25": (
            "scopecat.measurement-transform/right/derive%2F%25/inputs/source%2F%25"
        ),
    }

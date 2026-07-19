from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.frontend.graph_validation import verify_assembly_graph
from scopecat.kernel.errors import CheckFailed


def _semantic(name: str = "test.scale") -> sc.MeasurementTransformSemanticContract:
    return sc.MeasurementTransformSemanticContract(
        id=name,
        version="1",
        parameters={"scale": 2},
    )


def _transform(
    id: str,  # noqa: A002
    *,
    source: str,
    output: str,
) -> sc.MeasurementTransform:
    return sc.measurement_transform(
        id,
        semantic=_semantic(),
        inputs={"source": source},
        outputs={"result": output},
    )


def test_measurement_transform_captures_ordered_local_product_bindings() -> None:
    semantic = _semantic()
    transform = sc.measurement_transform(
        "derive",
        semantic=semantic,
        inputs={"left": "raw-a", "right": "raw-b"},
        outputs={"sum": "sum", "difference": "difference"},
    )

    assert transform.id == "derive"
    assert transform.semantic == semantic
    assert transform.semantic is semantic
    assert tuple(
        (role, product_id.qualified_name)
        for role, product_id in transform.input_bindings
    ) == (("left", "raw-a"), ("right", "raw-b"))
    assert tuple(
        (role, product_id.qualified_name)
        for role, product_id in transform.output_bindings
    ) == (("sum", "sum"), ("difference", "difference"))


def test_measurement_transform_validates_authoring_ingress() -> None:
    with pytest.raises(ValueError, match="non-empty role"):
        sc.measurement_transform(
            "derive",
            semantic=_semantic(),
            outputs={"": "derived"},
        )
    with pytest.raises(ValueError, match="at least one output"):
        sc.measurement_transform(
            "derive",
            semantic=_semantic(),
            outputs={},
        )


def test_module_requires_transform_products_and_unique_ids() -> None:
    transform = _transform("derive", source="raw", output="derived")

    with pytest.raises(ValueError, match="undeclared local product 'raw'"):
        (
            sc.module("test.transform.missing")
            .product("derived")
            .measurement_transforms(transform)
            .build()
        )
    with pytest.raises(ValueError, match="ids must be unique"):
        (
            sc.module("test.transform.duplicate")
            .product("raw", "derived")
            .measurement_transforms(transform, transform)
        )


def test_nested_measurement_transform_is_hygienically_scoped() -> None:
    child = (
        sc.module("test.transform.child")
        .product("raw", "derived")
        .measurement_transforms(_transform("derive", source="raw", output="derived"))
        .build()
    )
    nested = child.instantiate("nested")
    root = sc.module("test.transform.root").use(nested).build()

    graph = elaborate_module(root).semantic_graph
    [transform] = graph.measurement_transforms
    assert transform.id.qualified_name == "nested/derive"
    assert tuple(
        (role, product_id.qualified_name) for role, product_id in transform.inputs
    ) == (("source", "nested/raw"),)
    assert tuple(
        (role, product_id.qualified_name) for role, product_id in transform.outputs
    ) == (("result", "nested/derived"),)


def test_semantic_transform_graph_is_canonical_topological_order() -> None:
    first = _transform("first", source="raw", output="middle")
    second = _transform("second", source="middle", output="derived")
    module = (
        sc.module("test.transform.order")
        .product("raw", "middle", "derived")
        .measurement_transforms(second, first)
        .build()
    )

    graph = verify_assembly_graph(elaborate_module(module)).semantic_graph.graph
    assert tuple(
        transform.id.qualified_name for transform in graph.measurement_transforms
    ) == ("first", "second")


def test_semantic_transform_cycle_is_rejected() -> None:
    module = (
        sc.module("test.transform.cycle")
        .product("left", "right")
        .measurement_transforms(
            _transform("left-from-right", source="right", output="left"),
            _transform("right-from-left", source="left", output="right"),
        )
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        verify_assembly_graph(elaborate_module(module))
    assert "semantic_measurement_transform_cycle" in {
        problem.code for problem in error.value.problems
    }


def test_domain_and_transform_cannot_own_the_same_product() -> None:
    program = sc.domain_program(
        "program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        results={"raw": None},
    )
    module = (
        sc.module("test.transform.owner")
        .product("source", "raw")
        .measurement_transforms(_transform("derive", source="source", output="raw"))
        .build()
    )
    execution = sc.domain_execution(
        program,
        results={"raw": module.products["raw"]},
    )

    with pytest.raises(CheckFailed) as error:
        verify_assembly_graph(elaborate_module(module, (execution,)))
    assert "semantic_product_producer_duplicate" in {
        problem.code for problem in error.value.problems
    }

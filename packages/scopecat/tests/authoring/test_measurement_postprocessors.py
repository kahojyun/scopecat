from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.frontend.graph_validation import verify_assembly_graph
from scopecat.kernel.errors import CheckFailed
from scopecat.measurements.results import MeasurementValue


def _identity(value: MeasurementValue) -> dict[str, MeasurementValue]:
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
        (
            sc.module_body(id="test.postprocessor.missing")
            .product("derived")
            .measurement_postprocessors(postprocessor)
            .build()
        )
    with pytest.raises(
        ValueError,
        match="duplicate module measurement postprocessor ids",
    ):
        (
            sc.module_body(id="test.postprocessor.duplicate")
            .product("raw", "derived")
            .measurement_postprocessors(postprocessor, postprocessor)
            .build()
        )


def test_postprocessor_reads_child_product_and_is_hygienically_scoped() -> None:
    child = sc.module_body(id="test.postprocessor.source").product("raw").build()
    nested = child.instantiate("nested")
    builder = (
        sc.module_body(id="test.postprocessor.parent").use(nested).product("derived")
    )
    postprocessor = sc.measurement_postprocessor(
        "derive",
        input=nested.products.raw,
        outputs={"result": builder.products.derived},
        kernel=_identity,
    )
    module = builder.measurement_postprocessors(postprocessor).build()

    [lowered] = elaborate_module(module.ir).semantic_graph.measurement_postprocessors
    assert lowered.input.qualified_name == "nested/raw"
    assert lowered.outputs[0][1].qualified_name == "derived"

    nested_module = (
        sc.module_body(id="test.postprocessor.child")
        .product("raw", "derived")
        .measurement_postprocessors(
            _postprocessor("derive", source="raw", output="derived")
        )
        .build()
    )
    root = (
        sc.module_body(id="test.postprocessor.root")
        .use(nested_module.instantiate("nested"))
        .build()
    )
    [scoped] = elaborate_module(root.ir).semantic_graph.measurement_postprocessors
    assert scoped.id.qualified_name == "nested/derive"
    assert scoped.input.qualified_name == "nested/raw"


def test_postprocessor_chaining_is_rejected() -> None:
    module = (
        sc.module_body(id="test.postprocessor.chain")
        .product("raw", "middle", "derived")
        .measurement_postprocessors(
            _postprocessor("first", source="raw", output="middle"),
            _postprocessor("second", source="middle", output="derived"),
        )
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        verify_assembly_graph(elaborate_module(module.ir))
    assert {problem.code for problem in error.value.problems} == {
        "semantic_measurement_postprocessor_chaining_unsupported"
    }


def test_domain_and_postprocessor_cannot_own_the_same_product() -> None:
    program = sc.domain_program(
        "program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        results={"raw": None},
    )
    builder = (
        sc.module_body(id="test.postprocessor.owner")
        .product("source", "raw")
        .measurement_postprocessors(
            _postprocessor("derive", source="source", output="raw")
        )
    )
    module = builder.domain(
        sc.domain_execution(program, results={"raw": builder.products.raw})
    ).build()

    with pytest.raises(CheckFailed) as error:
        verify_assembly_graph(elaborate_module(module.ir))
    assert "semantic_product_producer_duplicate" in {
        problem.code for problem in error.value.problems
    }

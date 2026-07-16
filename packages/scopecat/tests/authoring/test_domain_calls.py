from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.typed.program import ValueInput
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.payloads import PayloadValue
from scopecat.planning.authoring import resolve_experiment
from scopecat.planning.coverage import program_execution_coverage
from tests.testkit.authoring import load_config


def _domain_module() -> tuple[sc.ExperimentModule, sc.DomainProgramDef, object]:
    value_type = sc.ScalarType(sc.IntType(minimum=0))
    body = object()
    program = sc.domain_program(
        "x-count-program",
        dialect_id="test.quantum",
        dialect_version="1",
        body=body,
        inputs={"x_count": value_type},
        results={"counts": {"kind": "counts"}},
    )
    module = (
        sc.module("test.domain.child")
        .inputs(sc.input("x_count", value_type))
        .product("counts", unit="count", dtype="int64")
        .build()
    )
    return module, program, body


def test_domain_execution_rejects_unknown_or_missing_bindings() -> None:
    value_type = sc.ScalarType(sc.IntType())
    product_module = sc.module("test.domain.products").product("result").build()
    program = sc.domain_program(
        "program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        inputs={"value": value_type},
        results={"result": None},
    )

    with pytest.raises(ValueError, match="unknown"):
        sc.domain_execution(
            program,
            inputs={"value": 1, "typo": 2},
            results={"result": product_module.products["result"]},
        )
    with pytest.raises(ValueError, match="missing"):
        sc.domain_execution(
            program,
            inputs={},
            results={"result": product_module.products["result"]},
        )


def test_domain_execution_captures_literal_inputs_at_authoring_ingress() -> None:
    body = object()
    payload = PayloadValue(schema_id="test.program", payload=body)
    program = sc.domain_program(
        "program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        inputs={"payload": sc.ScalarType(sc.PayloadType("test.program"))},
    )

    execution = sc.domain_execution(program, inputs={"payload": payload})
    payload.schema_id = "mutated"

    captured = execution.input_bindings[0][1]
    assert isinstance(captured, PayloadValue)
    assert captured is not payload
    assert captured.schema_id == "test.program"
    assert captured.payload is body

    with pytest.raises(ValueError, match="finite"):
        sc.domain_execution(program, inputs={"payload": float("nan")})


def test_domain_execution_must_bind_a_product_from_the_template_module() -> None:
    program = sc.domain_program(
        "program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        results={"result": None},
    )
    local = sc.module("test.domain.local").product("result").build()
    foreign = sc.module("test.domain.foreign").product("result").build()
    execution = sc.domain_execution(
        program,
        results={"result": foreign.products["result"]},
    )

    with pytest.raises(CheckFailed) as error:
        local.template("test.domain", kind="test").domain(execution).build()
    assert "domain_execution_product_foreign_instance" in {
        problem.code for problem in error.value.problems
    }


def test_template_rejects_a_second_domain_execution() -> None:
    program = sc.domain_program(
        "program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
    )
    execution = sc.domain_execution(program)
    builder = (
        sc.module("test.domain.single")
        .build()
        .template(
            "test.domain",
            kind="test",
        )
    )

    with pytest.raises(ValueError, match="already has a domain execution"):
        builder.domain(execution).domain(execution)


def test_domain_execution_rejects_execute_stage_compute_input() -> None:
    value_type = sc.ScalarType(sc.IntType())
    compute = sc.compute(
        "compute",
        fn=lambda: 1,
        output_type=value_type,
    )
    program = sc.domain_program(
        "program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        inputs={"value": value_type},
        results={"result": None},
    )
    module = (
        sc.module("test.domain.execute-input")
        .computes(compute)
        .product("result")
        .build()
    )
    execution = sc.domain_execution(
        program,
        inputs={"value": compute.output},
        results={"result": module.products["result"]},
    )

    with pytest.raises(CheckFailed) as error:
        elaborate_module(module, execution)
    assert "semantic_domain_execution_input_stage_unavailable" in {
        problem.code for problem in error.value.problems
    }


def test_template_domain_execution_lowers_plan_inputs_and_composed_product_uses() -> (
    None
):
    child, program, body = _domain_module()
    wrapper_x_count = sc.input("x_count", sc.ScalarType(sc.IntType(minimum=0)))
    inner = child.instantiate("inner", x_count=wrapper_x_count)
    wrapper = (
        sc.module("test.domain.wrapper").inputs(wrapper_x_count).use(inner).build()
    )
    point_x_count = sc.point(
        "x_count",
        sc.ScalarType(sc.IntType(minimum=0)),
    )
    outer = wrapper.instantiate("outer", x_count=point_x_count)
    root = sc.module("test.domain.root").use(outer).build()
    selected_product = outer.products["inner/counts"]
    execution = sc.domain_execution(
        program,
        inputs={"x_count": point_x_count},
        results={"counts": selected_product},
    )

    assembly = elaborate_module(root, execution)
    graph = assembly.semantic_graph
    assert graph.domain_execution is not None
    assert graph.domain_execution.program.id.qualified_name == "x-count-program"
    assert graph.domain_execution.results[0][1].qualified_name == ("outer/inner/counts")

    template = (
        root.template("test.domain", kind="domain")
        .domain(execution)
        .scan(sc.axis(point_x_count, (1, 2)))
        .record_product(selected_product, record_id="counts_first")
        .record_product(selected_product, record_id="counts_second")
        .build()
    )
    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )
    typed = resolved.experiment

    assert typed.instrument_product_producers == ()
    assert len(typed.domain_product_producers) == 1
    typed_execution = typed.domain_execution
    assert typed_execution is not None
    assert typed_execution.program.body is body
    assert isinstance(typed_execution.inputs["x_count"], ValueInput)
    result = typed_execution.results[0]
    assert result.product_use_ids == tuple(use.id for use in typed.product_uses)
    assert len(result.product_use_ids) == 2

    coverage = program_execution_coverage(typed)
    assert ("domain_execution", "domain") in {
        (task.kind, task.id) for task in coverage.tasks
    }
    assert {task.id for task in coverage.tasks if task.kind == "product"} == {
        use.id.value for use in typed.product_uses
    }


def test_domain_literal_input_namespace_does_not_collide_with_compute() -> None:
    value_type = sc.ScalarType(sc.IntType())
    compute = sc.compute(
        "domain",
        fn=_identity_value,
        inputs={"value": 1},
        output_type=value_type,
    )
    program = sc.domain_program(
        "program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        inputs={"value": value_type},
        results={"result": None},
    )
    module = (
        sc.module("test.domain.literal-namespace")
        .computes(compute)
        .product("result")
        .build()
    )
    execution = sc.domain_execution(
        program,
        inputs={"value": 2},
        results={"result": module.products["result"]},
    )

    graph = elaborate_module(module, execution).semantic_graph
    value_ids = {definition.id.qualified_name for definition in graph.value_defs}
    assert "domain/inputs/value" in value_ids
    assert "domain_execution/domain/inputs/value" in value_ids


def _identity_value(value: object) -> object:
    return value

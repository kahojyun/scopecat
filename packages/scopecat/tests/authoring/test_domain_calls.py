from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.typed.program import ValueInput
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.payloads import PayloadValue
from scopecat.planning.authoring import resolve_experiment
from scopecat.planning.coverage import program_execution_coverage
from tests.testkit.authoring import load_config


def _domain_module() -> tuple[sc.ExperimentModule, sc.ValueRef, object]:
    value_type = sc.ScalarType(sc.IntType(minimum=0))
    x_count = sc.input("x_count", value_type)
    body = object()
    program = sc.domain_program(
        "x-count-program",
        dialect_id="test.quantum",
        dialect_version="1",
        body=body,
        inputs={"x_count": value_type},
        results={"counts": {"kind": "counts"}},
    )
    call = sc.domain_call(
        "execute",
        program,
        inputs={"x_count": x_count},
        results={"counts": "counts"},
    )
    module = (
        sc.module("test.domain.child")
        .inputs(x_count)
        .product("counts", unit="count", dtype="int64")
        .domain_calls(call)
        .build()
    )
    return module, x_count, body


def test_domain_call_rejects_unknown_or_missing_bindings() -> None:
    value_type = sc.ScalarType(sc.IntType())
    program = sc.domain_program(
        "program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        inputs={"value": value_type},
        results={"result": None},
    )

    with pytest.raises(ValueError, match="unknown"):
        sc.domain_call(
            "call",
            program,
            inputs={"value": 1, "typo": 2},
            results={"result": "result"},
        )
    with pytest.raises(ValueError, match="missing"):
        sc.domain_call(
            "call",
            program,
            inputs={},
            results={"result": "result"},
        )
    with pytest.raises(TypeError, match="unsupported"):
        sc.domain_call(
            "call",
            program,
            inputs={"value": object()},  # pyright: ignore[reportArgumentType]
            results={"result": "result"},
        )
    with pytest.raises(TypeError, match="local products"):
        sc.domain_call(
            "call",
            program,
            inputs={"value": 1},
            results={"result": object()},  # pyright: ignore[reportArgumentType]
        )


def test_domain_program_rejects_non_value_type_ports() -> None:
    with pytest.raises(TypeError, match="ValueType"):
        sc.domain_program(
            "program",
            dialect_id="test",
            dialect_version="1",
            body=object(),
            inputs={"value": object()},  # pyright: ignore[reportArgumentType]
        )


def test_domain_call_captures_literal_inputs_at_authoring_ingress() -> None:
    body = object()
    payload = PayloadValue(schema_id="test.program", payload=body)
    program = sc.domain_program(
        "program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        inputs={"payload": sc.ScalarType(sc.PayloadType("test.program"))},
    )

    call = sc.domain_call("call", program, inputs={"payload": payload})
    payload.schema_id = "mutated"

    captured = call.input_bindings[0][1]
    assert isinstance(captured, PayloadValue)
    assert captured is not payload
    assert captured.schema_id == "test.program"
    assert captured.payload is body

    with pytest.raises(ValueError, match="finite"):
        sc.domain_call("non-finite", program, inputs={"payload": float("nan")})


def test_domain_call_must_bind_a_local_module_product() -> None:
    program = sc.domain_program(
        "program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        results={"result": None},
    )
    call = sc.domain_call(
        "call",
        program,
        results={"result": "foreign"},
    )

    with pytest.raises(ValueError, match="undeclared local product"):
        sc.module("test.domain.local-product").domain_calls(call).build()


def test_domain_call_rejects_execute_stage_compute_input() -> None:
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
    call = sc.domain_call(
        "call",
        program,
        inputs={"value": compute.output},
        results={"result": "result"},
    )
    module = (
        sc.module("test.domain.execute-input")
        .computes(compute)
        .product("result")
        .domain_calls(call)
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        elaborate_module(module)
    assert "semantic_domain_call_input_stage_unavailable" in {
        problem.code for problem in error.value.problems
    }


def test_nested_domain_call_lowers_plan_inputs_and_exact_product_uses(
    tmp_path: Path,
) -> None:
    child, _child_x_count, body = _domain_module()
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

    assembly = elaborate_module(root)
    graph = assembly.semantic_graph
    assert [program.id.qualified_name for program in graph.domain_programs] == [
        "outer/inner/x-count-program"
    ]
    assert [call.id.qualified_name for call in graph.domain_calls] == [
        "outer/inner/execute"
    ]
    assert graph.domain_calls[0].results[0][1].qualified_name == ("outer/inner/counts")

    selected_product = outer.products["inner/counts"]
    template = (
        root.template("test.domain", kind="domain")
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
    assert len(typed.domain_programs) == len(typed.domain_calls) == 1
    assert typed.domain_programs[0].body is body
    typed_call = typed.domain_calls[0]
    assert isinstance(typed_call.inputs["x_count"], ValueInput)
    result = typed_call.results[0]
    assert result.product_use_ids == tuple(use.id for use in typed.product_uses)
    assert len(result.product_use_ids) == 2

    coverage = program_execution_coverage(typed)
    assert ("domain_call", "outer/inner/execute") in {
        (task.kind, task.id) for task in coverage.tasks
    }
    assert {task.id for task in coverage.tasks if task.kind == "product"} == {
        use.id.value for use in typed.product_uses
    }


def test_domain_literal_input_namespace_does_not_collide_with_compute() -> None:
    value_type = sc.ScalarType(sc.IntType())
    compute = sc.compute(
        "same-id",
        fn=lambda value: value,
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
    call = sc.domain_call(
        "same-id",
        program,
        inputs={"value": 2},
        results={"result": "result"},
    )
    module = (
        sc.module("test.domain.literal-namespace")
        .computes(compute)
        .product("result")
        .domain_calls(call)
        .build()
    )

    graph = elaborate_module(module).semantic_graph
    value_ids = {definition.id.qualified_name for definition in graph.value_defs}
    assert "same-id/inputs/value" in value_ids
    assert "domain_calls/same-id/inputs/value" in value_ids

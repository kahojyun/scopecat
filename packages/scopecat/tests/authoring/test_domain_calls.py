from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.frontend.graph_validation import verify_assembly_graph
from scopecat.compiler.typed.program import (
    ValueInput,
    core_acquisitions,
    core_domain_executions,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.planning.authoring import resolve_experiment
from tests.testkit.authoring import load_config, template_fixture


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
        sc.module_body(id="test.domain.child")
        .inputs(sc.input("x_count", value_type))
        .product("counts", unit="count", dtype="int64")
        .build()
    )
    return module, program, body


def test_domain_execution_rejects_unknown_or_missing_bindings() -> None:
    value_type = sc.ScalarType(sc.IntType())
    product_module = sc.module_body(id="test.domain.products").product("result").build()
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


def test_domain_compiler_inputs_are_a_distinct_typed_namespace() -> None:
    value_type = sc.ScalarType(sc.IntType())
    program = sc.domain_program(
        "program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        inputs={"value": value_type},
        compiler_inputs={"calibration_revision": value_type},
    )
    execution = sc.domain_execution(
        program,
        inputs={"value": 3},
        compiler_inputs={"calibration_revision": 7},
    )

    semantic = elaborate_module(
        sc.module_body(id="test.domain.compiler-inputs").domain(execution).build()
    ).semantic_graph.domain_executions[0]

    assert tuple(port.id for port in semantic.program.input_ports) == ("value",)
    assert tuple(port.id for port in semantic.program.compiler_input_ports) == (
        "calibration_revision",
    )
    assert tuple(name for name, _use in semantic.inputs) == ("value",)
    assert tuple(name for name, _use in semantic.compiler_inputs) == (
        "calibration_revision",
    )


def test_domain_program_rejects_overlapping_input_namespaces() -> None:
    value_type = sc.ScalarType(sc.IntType())

    with pytest.raises(ValueError, match="ids must be unique"):
        sc.domain_program(
            "program",
            dialect_id="test",
            dialect_version="1",
            body=object(),
            inputs={"value": value_type},
            compiler_inputs={"value": value_type},
        )


def test_domain_execution_binds_declared_resource_roles_and_source_anchor() -> None:
    program = sc.domain_program(
        "controller-program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        results={"counts": None},
        resources={"controller": ("run-program",)},
    )
    builder = (
        sc.module_body(id="test.domain.resources")
        .resource("controller", requires=("run-program",))
        .product("counts", unit="count", dtype="int64")
    )
    execution = sc.domain_execution(
        program,
        id="run-controller",
        results={"counts": builder.products.counts},
        resources={"controller": "controller"},
    )

    assembly = elaborate_module(builder.domain(execution).build())
    semantic = assembly.semantic_graph.domain_executions[0]

    assert semantic.resources == (
        ("controller", logical_resource_port_id("controller")),
    )
    assert semantic.program.resource_ports[0].capabilities == ("run-program",)
    assert assembly.source_map.domain_sources[0][0] == "run-controller"
    assert assembly.source_map.domain_sources[0][1].kind == "domain"


def test_domain_resource_role_checks_module_capabilities() -> None:
    program = sc.domain_program(
        "controller-program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        resources={"controller": ("run-program",)},
    )
    builder = sc.module_body(id="test.domain.bad-resource").resource("controller")
    execution = sc.domain_execution(
        program,
        resources={"controller": "controller"},
    )

    with pytest.raises(CheckFailed) as error:
        builder.domain(execution).build()

    assert error.value.problems[0].code == "domain_resource_capability_mismatch"


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

    captured = execution.input_bindings[0][1]
    assert isinstance(captured, PayloadValue)
    assert captured is payload
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
    local = sc.module_body(id="test.domain.local").product("result").build()
    foreign = sc.module_body(id="test.domain.foreign").product("result").build()
    execution = sc.domain_execution(
        program,
        results={"result": foreign.products["result"]},
    )

    with pytest.raises(CheckFailed) as error:
        local.domain(execution)
    assert "domain_execution_product_foreign_instance" in {
        problem.code for problem in error.value.problems
    }


def test_module_preserves_ordered_domain_executions() -> None:
    program = sc.domain_program(
        "program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
    )
    first = sc.domain_execution(program, id="first")
    second = sc.domain_execution(program, id="second")
    module = (
        sc.module_body(id="test.domain.single").domain(first).domain(second).build()
    )
    template = template_fixture(module, id="test.domain", kind="test")

    assert tuple(call.id for call in template.module.domain_executions) == (
        "first",
        "second",
    )


def test_composed_domain_effects_are_scoped_per_module_instance() -> None:
    program = sc.domain_program(
        "program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        results={"result": None},
    )
    base = sc.module_body(id="test.domain.reusable").product("result").build()
    child = base.domain(
        sc.domain_execution(
            program,
            id="call",
            results={"result": base.products["result"]},
        )
    )
    right = child.instantiate("right")
    left = child.instantiate("left")
    root = sc.module_body(id="test.domain.composed").use(right, left).build()

    assembly = elaborate_module(root)

    assert tuple(
        execution.id for execution in assembly.semantic_graph.domain_executions
    ) == ("right/call", "left/call")
    assert tuple(
        execution.results[0][1].qualified_name
        for execution in assembly.semantic_graph.domain_executions
    ) == ("right/result", "left/result")


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
    base = (
        sc.module_body(id="test.domain.execute-input")
        .computes(compute)
        .product("result")
        .build()
    )
    execution = sc.domain_execution(
        program,
        inputs={"value": compute.output},
        results={"result": base.products["result"]},
    )
    module = base.domain(execution)

    with pytest.raises(CheckFailed) as error:
        verify_assembly_graph(elaborate_module(module))
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
        sc.module_body(id="test.domain.wrapper")
        .inputs(wrapper_x_count)
        .use(inner)
        .build()
    )
    point_x_count = sc.coordinate(
        "x_count",
        sc.ScalarType(sc.IntType(minimum=0)),
    )
    outer = wrapper.instantiate("outer", x_count=point_x_count)
    root = sc.module_body(id="test.domain.root").use(outer).build()
    selected_product = outer.products["inner/counts"]
    execution = sc.domain_execution(
        program,
        inputs={"x_count": point_x_count},
        results={"counts": selected_product},
    )

    root = root.domain(execution)
    assembly = elaborate_module(root)
    graph = assembly.semantic_graph
    assert len(graph.domain_executions) == 1
    assert graph.domain_executions[0].program.id.qualified_name == "x-count-program"
    assert graph.domain_executions[0].results[0][1].qualified_name == (
        "outer/inner/counts"
    )

    template = template_fixture(
        root,
        id="test.domain",
        kind="domain",
        scans=(sc.axis(point_x_count, (1, 2)),),
        records=(
            sc.record_product(selected_product, record_id="counts_first"),
            sc.record_product(selected_product, record_id="counts_second"),
        ),
    )
    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )
    typed = resolved.experiment

    assert core_acquisitions(typed) == ()
    typed_execution = core_domain_executions(typed)[0]
    assert typed_execution.program.body is body
    assert isinstance(typed_execution.inputs["x_count"], ValueInput)
    result = typed_execution.results[0]
    assert result.product_id.qualified_name == selected_product.id
    assert result.product_use_ids == tuple(use.id for use in typed.product_uses)
    assert len(result.product_use_ids) == 2


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
    base = (
        sc.module_body(id="test.domain.literal-namespace")
        .computes(compute)
        .product("result")
        .build()
    )
    execution = sc.domain_execution(
        program,
        inputs={"value": 2},
        results={"result": base.products["result"]},
    )
    module = base.domain(execution)

    graph = elaborate_module(module).semantic_graph
    value_ids = {definition.id.qualified_name for definition in graph.value_defs}
    assert "domain/inputs/value" in value_ids
    assert "domain_execution/program/inputs/value" in value_ids


def _identity_value(value: object) -> object:
    return value

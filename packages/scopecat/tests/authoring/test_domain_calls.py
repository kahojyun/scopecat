from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.frontend.graph_validation import verify_assembly_graph
from scopecat.compiler.linking.linked import materialize_linked_points
from scopecat.compiler.semantic.value_expressions import TableValue
from scopecat.compiler.typed.domain_results import domain_result_closure
from scopecat.compiler.typed.program import (
    ValueInput,
    core_acquisitions,
    core_domain_executions,
)
from scopecat.graph.table_values import LiteralTableSource
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.payloads import PayloadValue
from scopecat.sdk.domain._bridge import (
    make_domain_batch_request,
    make_domain_call_view,
)
from tests.testkit.authoring import link_invocation, load_config, template_fixture


def _domain_module() -> tuple[sc.ExperimentModule[...], sc.DomainProgramDef, object]:
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
        sc.procedure(id="test.domain.child")
        .inputs(sc.input("x_count", value_type))
        .product("counts", unit="count", dtype="int64")
        .build()
    )
    return module, program, body


def test_domain_execution_rejects_unknown_or_missing_bindings() -> None:
    value_type = sc.ScalarType(sc.IntType())
    product_module = sc.procedure(id="test.domain.products").product("result").build()
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
        sc.procedure(id="test.domain.compiler-inputs").domain(execution).build().ir
    ).domain_executions[0]

    assert tuple(port.id for port in semantic.program.input_ports) == ("value",)
    assert tuple(port.id for port in semantic.program.compiler_input_ports) == (
        "calibration_revision",
    )
    assert tuple(name for name, _use in semantic.inputs) == ("value",)
    assert tuple(name for name, _use in semantic.compiler_inputs) == (
        "calibration_revision",
    )


def test_table_module_input_reaches_domain_batch_through_nested_forwarding() -> None:
    table_type = sc.TableType(
        columns=(
            sc.TableColumn("id", sc.ScalarType(sc.IntType())),
            sc.TableColumn("gain", sc.ScalarType(sc.FloatType())),
        ),
        primary_key=("id",),
    )
    program = sc.domain_program(
        "table-program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        compiler_inputs={"rows": table_type},
    )
    leaf_rows = sc.input("rows", table_type)
    leaf = (
        sc.procedure(id="test.domain.table-leaf")
        .inputs(leaf_rows)
        .domain(
            sc.domain_execution(
                program,
                id="compile",
                compiler_inputs={"rows": leaf_rows},
            )
        )
        .build()
    )
    middle_rows = sc.input("rows", table_type)
    middle = (
        sc.procedure(id="test.domain.table-middle")
        .inputs(middle_rows)
        .use(leaf.instantiate("leaf", rows=middle_rows))
        .build()
    )
    root_rows = sc.input("rows", table_type)
    root = (
        sc.procedure(id="test.domain.table-root")
        .inputs(root_rows)
        .use(middle.instantiate("middle", rows=root_rows))
        .build()
    )
    linked = link_invocation(
        template_fixture(
            root,
            id="test.domain.table-forwarding",
            kind="domain",
        ).bind(rows=[{"id": 1, "gain": 0.5}, {"id": 2, "gain": 0.75}]),
        config_profile=load_config(),
    )

    [execution] = core_domain_executions(linked.program)
    table_value = execution.compiler_inputs["rows"].value
    assert isinstance(table_value, TableValue)
    assert isinstance(table_value.source, LiteralTableSource)

    points = materialize_linked_points(linked)
    call = make_domain_call_view(
        linked,
        execution.id,
        domain_result_closure(linked.program, execution.id),
    )
    request = make_domain_batch_request(
        call,
        points,
        (0,),
        batch_ordinal=0,
    )
    assert request.inputs.compiler_input("rows") == (
        ({"id": 1, "gain": 0.5}, {"id": 2, "gain": 0.75}),
    )


def test_domain_program_tables_are_compiler_inputs_only() -> None:
    table_type = sc.TableType(
        columns=(sc.TableColumn("id", sc.ScalarType(sc.IntType())),)
    )

    with pytest.raises(TypeError, match="use compiler_inputs"):
        sc.domain_program(
            "program",
            dialect_id="test",
            dialect_version="1",
            body=object(),
            inputs={"rows": table_type},  # pyright: ignore[reportArgumentType]
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
    local = sc.procedure(id="test.domain.local").product("result")
    foreign = sc.procedure(id="test.domain.foreign").product("result").build()
    execution = sc.domain_execution(
        program,
        results={"result": foreign.products["result"]},
    )

    with pytest.raises(CheckFailed) as error:
        local.domain(execution).build()
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
    module = sc.procedure(id="test.domain.single").domain(first).domain(second).build()
    template = template_fixture(module, id="test.domain", kind="test")

    assert tuple(
        call.id for call in template.definition.module.body.domain_executions
    ) == (
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
    base = sc.procedure(id="test.domain.reusable").product("result")
    child = base.domain(
        sc.domain_execution(
            program,
            id="call",
            results={"result": base.products["result"]},
        )
    ).build()
    right = child.instantiate("right")
    left = child.instantiate("left")
    root = sc.procedure(id="test.domain.composed").use(right, left).build()

    assembly = elaborate_module(root.ir)

    assert tuple(execution.id for execution in assembly.domain_executions) == (
        "right/call",
        "left/call",
    )
    assert tuple(
        execution.results[0][1].qualified_name
        for execution in assembly.domain_executions
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
        sc.procedure(id="test.domain.execute-input").computes(compute).product("result")
    )
    execution = sc.domain_execution(
        program,
        inputs={"value": compute.output},
        results={"result": base.products["result"]},
    )
    module = base.domain(execution).build()

    with pytest.raises(CheckFailed) as error:
        verify_assembly_graph(elaborate_module(module.ir))
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
        sc.procedure(id="test.domain.wrapper")
        .inputs(wrapper_x_count)
        .use(inner)
        .build()
    )
    point_x_count = sc.coordinate(
        "x_count",
        sc.ScalarType(sc.IntType(minimum=0)),
    )
    outer = wrapper.instantiate("outer", x_count=point_x_count)
    root = sc.procedure(id="test.domain.root").use(outer)
    selected_product = root.products["outer/inner/counts"]
    execution = sc.domain_execution(
        program,
        inputs={"x_count": point_x_count},
        results={"counts": selected_product},
    )

    root_module = root.domain(execution).build()
    assembly = elaborate_module(root_module.ir)
    assert len(assembly.domain_executions) == 1
    assert (
        assembly.domain_executions[0].program.symbol_id.qualified_name
        == "x-count-program"
    )
    assert assembly.domain_executions[0].results[0][1].qualified_name == (
        "outer/inner/counts"
    )

    template = template_fixture(
        root_module,
        id="test.domain",
        kind="domain",
        scans=(sc.axis(point_x_count, (1, 2)),),
        records=(
            sc.record_product(selected_product, record_id="counts_first"),
            sc.record_product(selected_product, record_id="counts_second"),
        ),
    )
    resolved = link_invocation(
        template.bind(),
        config_profile=load_config(),
    )
    typed = resolved.program

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
        sc.procedure(id="test.domain.literal-namespace")
        .computes(compute)
        .product("result")
    )
    execution = sc.domain_execution(
        program,
        inputs={"value": 2},
        results={"result": base.products["result"]},
    )
    module = base.domain(execution).build()

    graph = elaborate_module(module.ir).semantic_graph
    value_ids = {definition.id.qualified_name for definition in graph.value_defs}
    assert "domain/inputs/value" in value_ids
    assert "domain_execution/program/inputs/value" in value_ids


def _identity_value(value: object) -> object:
    return value

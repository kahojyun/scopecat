# pyright: reportUnusedFunction=false

from __future__ import annotations

from typing import Annotated

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
from tests.testkit.authoring import link_invocation, load_config


def _domain_table_type() -> sc.TableType:
    return sc.TableType(
        columns=(
            sc.TableColumn("id", sc.ScalarType(sc.IntType())),
            sc.TableColumn("gain", sc.ScalarType(sc.FloatType())),
        ),
        primary_key=("id",),
    )


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

    @sc.module(id="test.domain.child")
    def module(
        context: sc.ModuleContext,
        x_count: Annotated[sc.Input[int], sc.IntType(minimum=0)],
    ) -> None:
        del x_count
        context.product("counts", unit="count", dtype="int64")

    return module, program, body


def test_domain_execution_rejects_unknown_or_missing_bindings() -> None:
    value_type = sc.ScalarType(sc.IntType())

    @sc.module(id="test.domain.products")
    def product_module(context: sc.ModuleContext) -> None:
        context.product("result")

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

    @sc.module(id="test.domain.compiler-inputs")
    def module(context: sc.ModuleContext) -> None:
        context.domain(execution)

    semantic = elaborate_module(module.ir).domain_executions[0]

    assert tuple(port.id for port in semantic.program.input_ports) == ("value",)
    assert tuple(port.id for port in semantic.program.compiler_input_ports) == (
        "calibration_revision",
    )
    assert tuple(name for name, _use in semantic.inputs) == ("value",)
    assert tuple(name for name, _use in semantic.compiler_inputs) == (
        "calibration_revision",
    )


def test_table_module_input_reaches_domain_batch_through_nested_forwarding() -> None:
    table_type = _domain_table_type()
    program = sc.domain_program(
        "table-program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        compiler_inputs={"rows": table_type},
    )

    @sc.module(id="test.domain.table-leaf")
    def leaf(
        context: sc.ModuleContext,
        rows: Annotated[list[dict[str, object]], _domain_table_type()],
    ) -> None:
        context.domain(
            sc.domain_execution(
                program,
                id="compile",
                compiler_inputs={"rows": sc.input_ref(rows)},
            )
        )

    @sc.module(id="test.domain.table-middle")
    def middle(
        context: sc.ModuleContext,
        rows: Annotated[list[dict[str, object]], _domain_table_type()],
    ) -> None:
        context.call(leaf.instantiate("leaf", rows=sc.input_ref(rows)))

    @sc.module(id="test.domain.table-root")
    def root(
        context: sc.ModuleContext,
        rows: Annotated[list[dict[str, object]], _domain_table_type()],
    ) -> None:
        context.call(middle.instantiate("middle", rows=sc.input_ref(rows)))

    @sc.template(id="test.domain.table-forwarding", kind="domain")
    def template(
        experiment: sc.ExperimentContext,
        rows: Annotated[list[dict[str, object]], _domain_table_type()],
    ) -> None:
        experiment.run(root(rows))

    linked = link_invocation(
        template(rows=[{"id": 1, "gain": 0.5}, {"id": 2, "gain": 0.75}]),
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

    @sc.module(id="test.domain.foreign")
    def foreign(context: sc.ModuleContext) -> None:
        context.product("result")

    execution = sc.domain_execution(
        program,
        results={"result": foreign.products["result"]},
    )

    with pytest.raises(CheckFailed) as error:

        @sc.module(id="test.domain.local")
        def local(context: sc.ModuleContext) -> None:
            context.product("result")
            context.domain(execution)

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

    @sc.module(id="test.domain.single")
    def module(context: sc.ModuleContext) -> None:
        context.domain(first)
        context.domain(second)

    assert tuple(call.id for call in module.domain_executions) == (
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

    @sc.module(id="test.domain.reusable")
    def child(context: sc.ModuleContext) -> None:
        result = context.product("result")
        context.domain(
            sc.domain_execution(
                program,
                id="call",
                results={"result": result},
            )
        )

    right = child.instantiate("right")
    left = child.instantiate("left")

    @sc.module(id="test.domain.composed")
    def root(context: sc.ModuleContext) -> None:
        context.call(right)
        context.call(left)

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
    program = sc.domain_program(
        "program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        inputs={"value": value_type},
        results={"result": None},
    )

    @sc.module(id="test.domain.execute-input")
    def module(context: sc.ModuleContext) -> None:
        compute = context.compute(
            "compute",
            fn=lambda: 1,
            output_type=value_type,
        )
        result = context.product("result")
        context.domain(
            sc.domain_execution(
                program,
                inputs={"value": compute},
                results={"result": result},
            )
        )

    with pytest.raises(CheckFailed) as error:
        verify_assembly_graph(elaborate_module(module.ir))
    assert "semantic_domain_execution_input_stage_unavailable" in {
        problem.code for problem in error.value.problems
    }


def test_template_domain_execution_lowers_plan_inputs_and_composed_product_uses() -> (
    None
):
    child, program, body = _domain_module()

    @sc.module(id="test.domain.wrapper")
    def wrapper(
        context: sc.ModuleContext,
        x_count: Annotated[sc.Input[int], sc.IntType(minimum=0)],
    ) -> None:
        context.call(child.instantiate("inner", x_count=x_count))

    point_x_count = sc.coordinate(
        "x_count",
        sc.ScalarType(sc.IntType(minimum=0)),
    )

    @sc.module(id="test.domain.root")
    def root_module(
        context: sc.ModuleContext,
        x_count: Annotated[sc.Input[int], sc.IntType(minimum=0)],
    ) -> None:
        outer = wrapper.instantiate("outer", x_count=x_count)
        context.call(outer)
        context.domain(
            sc.domain_execution(
                program,
                inputs={"x_count": x_count},
                results={"counts": outer.products["inner/counts"]},
            )
        )

    assembly = elaborate_module(root_module.ir, x_count=point_x_count)
    assert len(assembly.domain_executions) == 1
    assert (
        assembly.domain_executions[0].program.symbol_id.qualified_name
        == "x-count-program"
    )
    assert assembly.domain_executions[0].results[0][1].qualified_name == (
        "outer/inner/counts"
    )

    @sc.template(id="test.domain", kind="domain")
    def template(experiment: sc.ExperimentContext) -> None:
        call = experiment.run(root_module(point_x_count))
        selected_product = call.products["outer/inner/counts"]
        experiment.scan(sc.axis(point_x_count, (1, 2)))
        experiment.record(selected_product, record_id="counts_first")
        experiment.record(selected_product, record_id="counts_second")

    resolved = link_invocation(
        template(),
        config_profile=load_config(),
    )
    typed = resolved.program

    assert core_acquisitions(typed) == ()
    typed_execution = core_domain_executions(typed)[0]
    assert typed_execution.program.body is body
    assert isinstance(typed_execution.inputs["x_count"], ValueInput)
    result = typed_execution.results[0]
    assert result.product_id.qualified_name == "root/outer/inner/counts"
    assert result.product_use_ids == tuple(use.id for use in typed.product_uses)
    assert len(result.product_use_ids) == 2


def test_domain_literal_input_namespace_does_not_collide_with_compute() -> None:
    value_type = sc.ScalarType(sc.IntType())
    program = sc.domain_program(
        "program",
        dialect_id="test",
        dialect_version="1",
        body=object(),
        inputs={"value": value_type},
        results={"result": None},
    )

    @sc.module(id="test.domain.literal-namespace")
    def module(context: sc.ModuleContext) -> None:
        context.compute(
            "domain",
            fn=_identity_value,
            inputs={"value": 1},
            output_type=value_type,
        )
        result = context.product("result")
        context.domain(
            sc.domain_execution(
                program,
                inputs={"value": 2},
                results={"result": result},
            )
        )

    graph = elaborate_module(module.ir).semantic_graph
    value_ids = {definition.id.qualified_name for definition in graph.value_defs}
    assert "domain/inputs/value" in value_ids
    assert "domain_execution/program/inputs/value" in value_ids


def _identity_value(value: object) -> object:
    return value

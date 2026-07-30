from __future__ import annotations

import pytest

import scopecat.authoring as authoring
from scopecat.authoring.scans import axis
from scopecat.authoring.templates import ExperimentInvocation
from scopecat.compiler.frontend.assembly_linking import bind_verified_assembly
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.compiler.typed.program import (
    ComputeEdge,
    CoreProgram,
)
from scopecat.config.environment import build_config_environment
from scopecat.graph.values import (
    OperationId,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.symbols import SymbolId
from scopecat.records.config import ConfigProfileSnapshot
from tests.testkit.authoring import link_invocation, load_config, template_fixture
from tests.testkit.local_materialization import materialize_local_execution


def _bind_program(
    invocation: ExperimentInvocation,
    config: ConfigProfileSnapshot,
) -> CoreProgram:
    environment = build_config_environment(config)
    compiled = compile_invocation(invocation)
    return bind_verified_assembly(compiled.assembly, environment)


def _echo_program(*, program: object) -> dict[str, object]:
    return {"program": program}


def _empty_payload() -> dict[str, object]:
    return {}


def _entity_scalar() -> authoring.ScalarType:
    return authoring.ScalarType(authoring.EntityType())


def _gate_table_type() -> authoring.TableType:
    return authoring.TableType(
        columns=(
            authoring.TableColumn("control", _entity_scalar()),
            authoring.TableColumn("target", _entity_scalar()),
        )
    )


def test_nested_module_requires_explicit_input_forwarding() -> None:
    value = authoring.input(
        "value",
        authoring.ScalarType(authoring.FloatType()),
    )
    child = authoring.procedure(id="test.nested_port.child").inputs(value).build()

    with pytest.raises(ValueError, match="must connect all inputs"):
        child.instantiate("child")

    outer_value = authoring.input("outer_value", value.value_type)
    root = (
        authoring.procedure(id="test.nested_port.root")
        .inputs(outer_value)
        .use(child.instantiate("child", value=outer_value))
        .build()
    )
    template = template_fixture(
        root,
        id="test.nested_port",
        kind="nested_port",
    )

    link_invocation(
        template.bind(outer_value=1),
        config_profile=load_config(),
    )


def test_scan_points_are_coerced_by_their_target_type() -> None:
    point = authoring.coordinate(
        "value",
        authoring.ScalarType(authoring.FloatType()),
    )
    module = authoring.procedure(id="test.scan_coercion").build()
    template = template_fixture(
        module,
        id="test.scan_coercion",
        kind="scan_coercion",
        scans=(axis(point, (1,)),),
    )

    resolved = link_invocation(
        template.bind(),
        config_profile=load_config(),
    )
    plan = materialize_local_execution(resolved)
    value = plan.points[0].coordinates["value"]

    assert value == 1.0
    assert isinstance(value, float)


def test_scan_points_reject_target_constraint_violation() -> None:
    with pytest.raises(authoring.ValueValidationError) as error:
        axis(
            authoring.coordinate(
                "count",
                authoring.ScalarType(authoring.IntType(minimum=1)),
            ),
            (0,),
        )

    assert error.value.path == ("scan", "values", 0)
    assert error.value.reason == "value must be at least 1"


def test_module_invocation_rejects_quantity_unit_and_table_schema_mismatch() -> None:
    frequency = authoring.input(
        "frequency",
        authoring.ScalarType(authoring.QuantityType(unit="GHz")),
    )
    quantity_child = (
        authoring.procedure(id="test.quantity_type.child").inputs(frequency).build()
    )
    duration = authoring.input(
        "duration",
        authoring.ScalarType(authoring.QuantityType(unit="ns")),
    )
    with pytest.raises(authoring.ValueValidationError, match=r"Quantity\[GHz\]"):
        quantity_child.instantiate("quantity-child", frequency=duration)

    float_gate_table = authoring.TableType(
        columns=(
            authoring.TableColumn(
                "control",
                authoring.ScalarType(authoring.FloatType()),
            ),
            authoring.TableColumn(
                "target",
                authoring.ScalarType(authoring.FloatType()),
            ),
        )
    )
    gates = authoring.input("gates", _gate_table_type())
    table_child = authoring.procedure(id="test.table_type.child").inputs(gates).build()
    rows = authoring.input("rows", float_gate_table)
    with pytest.raises(
        authoring.ValueValidationError,
        match=r"control: Scalar\[Entity\]",
    ):
        table_child.instantiate("table-child", gates=rows)


def test_compute_output_is_a_typed_child_input_edge() -> None:
    pulse = authoring.ScalarType(authoring.PayloadType("pulse"))
    program = authoring.input("program", pulse)
    consume = authoring.compute(
        "consume",
        fn=_echo_program,
        inputs={"program": program},
        output_type=authoring.ScalarType(authoring.PayloadType("consumed")),
    )
    child = (
        authoring.procedure(id="test.compute_edge.child")
        .inputs(program)
        .computes(consume)
        .build()
    )
    middle_program = authoring.input("program", pulse)
    middle = (
        authoring.procedure(id="test.compute_edge.middle")
        .inputs(middle_program)
        .use(child.instantiate("compute-child", program=middle_program))
        .build()
    )
    produce = authoring.compute(
        "produce",
        fn=_empty_payload,
        output_type=pulse,
    )
    parent = (
        authoring.procedure(id="test.compute_edge.parent")
        .computes(produce)
        .use(middle.instantiate("compute-middle", program=produce.output))
        .build()
    )

    assembly = elaborate_module(
        parent.ir,
    )
    consumer = next(
        operation
        for operation in assembly.semantic_graph.operations
        if operation.id.local_id == "consume"
    )
    program_use = dict(consumer.inputs)["program"]
    producer = next(
        operation
        for operation in assembly.semantic_graph.operations
        if operation.result_id == program_use.value_id
    )
    assert producer.id == OperationId(SymbolId(local_id="produce"))
    program = _bind_program(
        template_fixture(
            parent,
            id="test.compute_edge",
            kind="compute_edge",
        ).bind(),
        load_config(),
    )
    bound_consumer = next(
        node for node in program.compute_nodes if node.id.local_id == "consume"
    )
    bound_producer = next(
        node for node in program.compute_nodes if node.id.local_id == "produce"
    )
    program_edge = bound_consumer.inputs["program"]
    assert isinstance(program_edge, ComputeEdge)
    assert bound_producer.result.id == producer.result_id
    assert bound_producer.result.value_type == pulse
    assert program_edge.value_id == bound_producer.result.id
    assert program_edge.expected_type == bound_producer.result.value_type

    incompatible_program = authoring.input(
        "program",
        authoring.ScalarType(authoring.PayloadType("waveform")),
    )
    incompatible_child = (
        authoring.procedure(id="test.compute_edge.incompatible")
        .inputs(incompatible_program)
        .build()
    )
    incompatible_produce = authoring.compute(
        "produce",
        fn=_empty_payload,
        output_type=pulse,
    )
    with pytest.raises(authoring.ValueValidationError, match=r"Payload\[waveform\]"):
        incompatible_child.instantiate(
            "incompatible-child",
            program=incompatible_produce.output,
        )


def test_explicit_null_is_rejected_as_a_bound_value() -> None:
    required_label = authoring.input(
        "label",
        authoring.ScalarType(authoring.StringType()),
    )
    required = template_fixture(
        authoring.procedure(id="test.null.required").inputs(required_label).build(),
        id="test.null.required",
        kind="null",
    )

    with pytest.raises(CheckFailed) as error:
        link_invocation(
            required.bind(label=None),
            config_profile=load_config(),
        )
    assert error.value.problems[0].code == "module_input_type_mismatch"
    assert "value must not be null" in error.value.problems[0].message

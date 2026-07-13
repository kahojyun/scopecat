from __future__ import annotations

from enum import IntEnum, StrEnum

from scopecat._compiler.binding import bind_program
from scopecat._compiler.bound import BoundComputeOutput, BoundValue
from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.ids import NodeId
from scopecat._compiler.program import (
    ComputeEdge,
    TypedComputeNode,
    TypedPointSource,
    ValueInput,
    compute_result,
    set_state_field,
    typed_program,
)
from scopecat._content_identity import content_fingerprint
from scopecat._relations import col, literal_rows
from scopecat._value_expressions import as_value_expr
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity
from scopecat.models.state import PayloadRef
from scopecat.models.value import PayloadValue
from scopecat.value_types import (
    Entity,
    Float,
    Payload,
    Scalar,
    String,
    Table,
    TableColumn,
)
from scopecat.value_types import Quantity as QuantityType
from tests.support.authoring import load_config


class _FirstIntegerToken(IntEnum):
    ONE = 1


class _SecondIntegerToken(IntEnum):
    ONE = 1


class _TextToken(StrEnum):
    ONE = "one"


def test_content_fingerprint_preserves_primitive_enum_types() -> None:
    first = content_fingerprint(_FirstIntegerToken.ONE)

    assert first != content_fingerprint(1)
    assert first != content_fingerprint(_SecondIntegerToken.ONE)
    assert content_fingerprint(_TextToken.ONE) != content_fingerprint("one")


def test_bound_plan_uses_content_addressed_point_and_payload_identity() -> None:
    producer_id = NodeId(local_id="produce")
    consumer_id = NodeId(local_id="consume")
    unused_id = NodeId(local_id="unused-payload")
    program = typed_program(
        id="bound-identity",
        kind="compiler_test",
        point_source=TypedPointSource(
            expr=literal_rows([{"value": 1.0}, {"value": 1.0}, {"value": 2.0}]),
            value_type=Table(
                columns=(TableColumn("value", Scalar(Float())),),
                min_rows=3,
                max_rows=3,
            ),
        ),
        compute_nodes=(
            TypedComputeNode(
                id=consumer_id,
                inputs={
                    "value": ComputeEdge(
                        producer=producer_id,
                        value_type=Scalar(Float()),
                    )
                },
                output_type=Scalar(Payload("pulse_program")),
                fn=lambda *, value: {"value": value},
            ),
            TypedComputeNode(
                id=unused_id,
                output_type=Scalar(Payload("unused_program")),
                fn=lambda: {"unused": True},
            ),
            TypedComputeNode(
                id=producer_id,
                inputs={
                    "value": ValueInput(
                        value=as_value_expr(col("value")),
                        value_type=Scalar(Float()),
                    )
                },
                output_type=Scalar(Float()),
                fn=lambda *, value: value,
            ),
        ),
        state=(
            set_state_field(
                "source-0",
                capability_id="play_program",
                field_path="program",
                value=compute_result(consumer_id),
            ),
        ),
    )
    environment = validate_config_environment(load_config())

    plan = bind_program(program, environment)
    repeated = bind_program(program, environment)

    assert plan.valid
    assert [point.point_key for point in plan.points[:2]] == [
        plan.points[0].point_key,
        plan.points[0].point_key,
    ]
    assert plan.points[2].point_key != plan.points[0].point_key
    assert [point.occurrence for point in plan.points] == [0, 1, 0]
    assert len({point.point_uid for point in plan.points}) == 3
    assert [point.point_uid for point in plan.points] == [
        point.point_uid for point in repeated.points
    ]

    payload_ids: list[str] = []
    for point in plan.points:
        node_ids = [call.node_id for call in point.compute]
        assert node_ids.index(producer_id) < node_ids.index(consumer_id)
        consumer = next(call for call in point.compute if call.node_id == consumer_id)
        unused = next(call for call in point.compute if call.node_id == unused_id)
        assert consumer.inputs["value"] == BoundComputeOutput(producer_id)
        assert consumer.payload_id is not None
        assert unused.payload_id is None
        payload_ids.append(consumer.payload_id)

        state_value = point.desired_state[0].fields[0].value.root
        assert isinstance(state_value, PayloadRef)
        assert state_value.payload_id == consumer.payload_id

    assert payload_ids[0] == payload_ids[1]
    assert payload_ids[2] != payload_ids[0]


def test_point_source_enforces_complete_table_contract() -> None:
    programs = (
        typed_program(
            id="missing-required-column",
            kind="compiler_test",
            point_source=TypedPointSource(
                expr=literal_rows([{}]),
                value_type=Table(
                    columns=(TableColumn("required", Scalar(String())),),
                ),
            ),
        ),
        typed_program(
            id="unexpected-extra-column",
            kind="compiler_test",
            point_source=TypedPointSource(
                expr=literal_rows([{"declared": "ok", "extra": "no"}]),
                value_type=Table(
                    columns=(TableColumn("declared", Scalar(String())),),
                    allow_extra_columns=False,
                ),
            ),
        ),
        typed_program(
            id="duplicate-primary-key",
            kind="compiler_test",
            point_source=TypedPointSource(
                expr=literal_rows([{"id": "same"}, {"id": "same"}]),
                value_type=Table(
                    columns=(TableColumn("id", Scalar(String())),),
                    primary_key=("id",),
                ),
            ),
        ),
        typed_program(
            id="too-few-rows",
            kind="compiler_test",
            point_source=TypedPointSource(
                expr=literal_rows([]),
                value_type=Table(columns=(), min_rows=1),
            ),
        ),
    )
    environment = validate_config_environment(load_config())

    for program in programs:
        plan = bind_program(program, environment)
        assert not plan.valid
        assert plan.points == ()
        assert plan.problems[-1].code == "module_point_value_type_mismatch"


def test_point_source_rechecks_primary_key_after_entity_normalization() -> None:
    program = typed_program(
        id="normalized-entity-primary-key",
        kind="compiler_test",
        point_source=TypedPointSource(
            expr=literal_rows(
                [
                    {"subject": "q0"},
                    {
                        "subject": EntityRef(
                            id="q0",
                            kind="logical_device",
                        )
                    },
                ]
            ),
            value_type=Table(
                columns=(TableColumn("subject", Scalar(Entity())),),
                primary_key=("subject",),
            ),
            entity_column_ids=("subject",),
        ),
    )

    plan = bind_program(program, validate_config_environment(load_config()))

    assert not plan.valid
    assert plan.points == ()
    problem = next(
        problem
        for problem in plan.problems
        if problem.code == "module_point_value_type_mismatch"
    )
    assert "duplicates row 0" in problem.message


def test_compute_inputs_are_normalized_before_binding_and_hashing() -> None:
    node_id = NodeId(local_id="normalize-frequency")
    program = typed_program(
        id="normalized-compute-input",
        kind="compiler_test",
        point_source=TypedPointSource(
            expr=literal_rows(
                [
                    {"frequency": Quantity(value=5000.0, unit="MHz")},
                    {"frequency": Quantity(value=5.0, unit="GHz")},
                ]
            ),
            value_type=Table(
                columns=(
                    TableColumn(
                        "frequency",
                        Scalar(QuantityType(dimension="frequency")),
                    ),
                ),
            ),
        ),
        compute_nodes=(
            TypedComputeNode(
                id=node_id,
                inputs={
                    "frequency": ValueInput(
                        value=as_value_expr(col("frequency")),
                        value_type=Scalar(QuantityType(unit="GHz")),
                    )
                },
                output_type=Scalar(Float()),
                fn=lambda *, frequency: frequency.value,
            ),
        ),
    )

    plan = bind_program(program, validate_config_environment(load_config()))

    assert plan.valid
    calls = [point.compute[0] for point in plan.points]
    assert [call.inputs["frequency"] for call in calls] == [
        BoundValue(Quantity(value=5.0, unit="GHz")),
        BoundValue(Quantity(value=5.0, unit="GHz")),
    ]
    assert calls[0].cache_key == calls[1].cache_key


def test_compute_payload_input_rejects_mismatched_schema_before_unwrapping() -> None:
    node_id = NodeId(local_id="consume-payload")
    program = typed_program(
        id="mismatched-compute-payload",
        kind="compiler_test",
        point_source=TypedPointSource(
            expr=literal_rows(
                [
                    {
                        "payload": PayloadValue(
                            schema_id="source-payload",
                            payload={"value": 1},
                        )
                    }
                ]
            ),
            value_type=Table(
                columns=(TableColumn("payload", Scalar(Payload("source-payload"))),),
            ),
        ),
        compute_nodes=(
            TypedComputeNode(
                id=node_id,
                inputs={
                    "payload": ValueInput(
                        value=as_value_expr(col("payload")),
                        value_type=Scalar(Payload("expected-payload")),
                    )
                },
                output_type=Scalar(Float()),
                fn=lambda *, payload: float(payload["value"]),
            ),
        ),
    )

    plan = bind_program(program, validate_config_environment(load_config()))

    assert not plan.valid
    assert plan.points[0].compute == ()
    problem = next(
        problem
        for problem in plan.problems
        if problem.code == "compute_node_input_binding_failed"
    )
    assert "expected payload 'expected-payload', got 'source-payload'" in (
        problem.message
    )


def test_compute_mapping_fingerprint_preserves_key_types_and_values() -> None:
    node_id = NodeId(local_id="consume-mapping")
    program = typed_program(
        id="mapping-fingerprint",
        kind="compiler_test",
        point_source=TypedPointSource(
            expr=literal_rows(
                [
                    {
                        "payload": PayloadValue(
                            schema_id="mapping",
                            payload={1: "a", "1": "b"},
                        )
                    },
                    {
                        "payload": PayloadValue(
                            schema_id="mapping",
                            payload={1: "z", "1": "b"},
                        )
                    },
                ]
            ),
            value_type=Table(
                columns=(TableColumn("payload", Scalar(Payload("mapping"))),),
            ),
        ),
        compute_nodes=(
            TypedComputeNode(
                id=node_id,
                inputs={
                    "payload": ValueInput(
                        value=as_value_expr(col("payload")),
                        value_type=Scalar(Payload("mapping")),
                    )
                },
                output_type=Scalar(Float()),
                fn=lambda *, payload: float(len(payload)),
            ),
        ),
    )

    plan = bind_program(program, validate_config_environment(load_config()))

    assert plan.valid
    assert plan.points[0].compute[0].cache_key != plan.points[1].compute[0].cache_key


def test_opaque_point_value_requires_explicit_stable_fingerprint() -> None:
    program = typed_program(
        id="opaque-point",
        kind="compiler_test",
        point_source=TypedPointSource(
            expr=literal_rows(
                [
                    {
                        "payload": PayloadValue(
                            schema_id="opaque",
                            payload=object(),
                        )
                    }
                ]
            ),
            value_type=Table(
                columns=(TableColumn("payload", Scalar(Payload("opaque"))),),
            ),
        ),
    )

    plan = bind_program(program, validate_config_environment(load_config()))

    assert not plan.valid
    assert plan.points == ()
    assert plan.problems[-1].code == "experiment_point_identity_failed"

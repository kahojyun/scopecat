from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import IntEnum, StrEnum

import pytest

from scopecat.compiler.relations.verification import (
    RelationPlanVerificationError,
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.semantic.model import (
    ImplementationId,
    LocalPythonImplementation,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    ComputeEdge,
    LogicalResourceRequirement,
    TypedComputeNode,
    ValueInput,
    set_state_field,
)
from scopecat.config.environment import build_config_environment
from scopecat.execution.local.program import (
    ApplyStateOperation,
    BoundInput,
    ComputeOperation,
    OutputInput,
)
from scopecat.graph.relations.model import (
    CellValue,
    RelationExpr,
    lit,
    literal_rows,
    point_col,
)
from scopecat.graph.relations.point_domain import point_axis_values
from scopecat.graph.values import (
    ComputeOutput,
    OperationId,
    ValueId,
    operation_result_id,
)
from scopecat.kernel.content_identity import content_fingerprint
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    logical_resource_port_id,
)
from scopecat.kernel.state import PayloadRef
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import (
    Bool,
    Float,
    Int,
    Payload,
    Scalar,
    String,
    Table,
    TableColumn,
)
from scopecat.kernel.value_types import Quantity as QuantityType
from tests.testkit.authoring import load_config
from tests.testkit.local_materialization import (
    materialize_local_execution,
    operations_of_type,
)
from tests.testkit.materialized_effects import config_with_physical_resources
from tests.testkit.relation_plans import (
    scalar_value_expr,
    table_value_expr,
    value_expr,
)
from tests.testkit.typed_program import compute_result, link_program, typed_program


class _FirstIntegerToken(IntEnum):
    ONE = 1


class _SecondIntegerToken(IntEnum):
    ONE = 1


class _TextToken(StrEnum):
    ONE = "one"


def _operation_id(local_id: str) -> OperationId:
    return OperationId(SymbolId(local_id=local_id))


def _output(
    operation_id: OperationId,
    value_type: Scalar,
    *,
    value_id: ValueId | None = None,
) -> ComputeOutput:
    return ComputeOutput(
        id=value_id or operation_result_id(operation_id),
        value_type=value_type,
    )


def _implementation(
    operation_id: OperationId,
    kernel: Callable[..., object],
) -> LocalPythonImplementation:
    return LocalPythonImplementation(
        id=ImplementationId(f"python.{operation_id.qualified_name}.v1"),
        kernel=kernel,
    )


def _wrap_value(*, value: object) -> dict[str, object]:
    return {"value": value}


def _identity_value(*, value: object) -> object:
    return value


def _quantity_value(*, frequency: Quantity) -> float:
    return frequency.value


def _mapping_size(*, payload: Mapping[object, object]) -> float:
    return float(len(payload))


def _point_domain(
    rows: tuple[tuple[CellValue, ...], ...],
    value_type: Table,
) -> PointDomain:
    if not value_type.columns:
        return PointDomain(axes=())
    [column] = value_type.columns
    return PointDomain(
        axes=(
            point_axis_values(
                column.id,
                column.value_type,
                tuple(row[0] for row in rows),
            ),
        )
    )


def _point_bindings(value_type: Table) -> RelationTypeBindings:
    return RelationTypeBindings(point_row=RowType.from_table(value_type))


def _resource(value: str) -> LogicalResourcePortId:
    return logical_resource_port_id(value)


def test_content_fingerprint_preserves_primitive_enum_types() -> None:
    first = content_fingerprint(_FirstIntegerToken.ONE)

    assert first != content_fingerprint(1)
    assert first != content_fingerprint(_SecondIntegerToken.ONE)
    assert content_fingerprint(_TextToken.ONE) != content_fingerprint("one")


@pytest.mark.parametrize(
    ("value", "value_type"),
    [
        (True, Scalar(Bool())),
        (3, Scalar(Int())),
        ("operate", Scalar(String())),
    ],
)
def test_bound_state_preserves_primitive_field_types(
    value: str | int | bool,
    value_type: Scalar,
) -> None:
    program = typed_program(
        id="primitive-state",
        kind="compiler_test",
        point_domain=_point_domain(
            ((),),
            Table(columns=()),
        ),
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=_resource("source-0"),
                capabilities=("configure",),
            ),
        ),
        state=(
            set_state_field(
                resource_port_id=_resource("source-0"),
                capability_id="configure",
                field_path="value",
                value=scalar_value_expr(lit(value), expected_type=value_type),
            ),
        ),
    )
    environment = build_config_environment(
        config_with_physical_resources({"source-0": ("configure",)})
    )

    plan = materialize_local_execution(link_program(program, environment))

    assert (
        operations_of_type(plan, ApplyStateOperation, point_index=0)[0]
        .targets[0]
        .value.root
        == value
    )
    assert type(
        operations_of_type(plan, ApplyStateOperation, point_index=0)[0]
        .targets[0]
        .value.root
    ) is type(value)


def test_effects_use_logical_point_and_point_local_payload_identity() -> None:
    producer_id = _operation_id("produce")
    consumer_id = _operation_id("consume")
    unused_id = _operation_id("a-unused-payload")
    producer_output_id = operation_result_id(producer_id)
    consumer_output_id = operation_result_id(consumer_id)
    point_type = Table(columns=(TableColumn("value", Scalar(Float())),))
    program = typed_program(
        id="bound-identity",
        kind="compiler_test",
        point_domain=_point_domain(
            ((1.0,), (1.0,), (2.0,)),
            point_type,
        ),
        compute_nodes=(
            TypedComputeNode(
                id=unused_id,
                implementation=_implementation(
                    unused_id,
                    lambda: {"unused": True},
                ),
                result=_output(unused_id, Scalar(Payload("unused_program"))),
            ),
            TypedComputeNode(
                id=producer_id,
                implementation=_implementation(producer_id, _identity_value),
                inputs={
                    "value": ValueInput(
                        value=value_expr(
                            point_col("value"),
                            expected_type=Scalar(Float()),
                            bindings=_point_bindings(point_type),
                        ),
                    )
                },
                result=_output(producer_id, Scalar(Float())),
            ),
            TypedComputeNode(
                id=consumer_id,
                implementation=_implementation(consumer_id, _wrap_value),
                inputs={
                    "value": ComputeEdge(
                        value_id=producer_output_id,
                        expected_type=Scalar(Float()),
                    )
                },
                result=_output(consumer_id, Scalar(Payload("pulse_program"))),
            ),
        ),
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=_resource("source-0"),
                capabilities=("play_program",),
            ),
        ),
        state=(
            set_state_field(
                resource_port_id=_resource("source-0"),
                capability_id="play_program",
                field_path="program",
                value=compute_result(consumer_output_id),
            ),
        ),
    )
    environment = build_config_environment(
        config_with_physical_resources({"source-0": ("play_program",)})
    )

    plan = materialize_local_execution(link_program(program, environment))
    repeated = materialize_local_execution(link_program(program, environment))

    assert [point.logical_id.logical_ordinal for point in plan.points] == [0, 1, 2]
    assert {
        (point.logical_id.domain_id.program_id, point.logical_id.domain_id.domain_id)
        for point in plan.points
    } == {("bound-identity", "root")}
    assert len({point.logical_id.value for point in plan.points}) == 3
    assert [point.logical_id.value for point in plan.points] == [
        point.logical_id.value for point in repeated.points
    ]

    payload_ids: list[str] = []
    [unused] = [
        call
        for call in operations_of_type(plan, ComputeOperation, point_index=0)
        if call.semantic_operation_id == unused_id.qualified_name
    ]
    assert unused.payload_slot is None
    for point in plan.points:
        node_ids = [
            call.semantic_operation_id
            for call in operations_of_type(
                plan, ComputeOperation, point_index=point.ordinal
            )
        ]
        assert node_ids.index(producer_id.qualified_name) < node_ids.index(
            consumer_id.qualified_name
        )
        consumer = next(
            call
            for call in operations_of_type(
                plan, ComputeOperation, point_index=point.ordinal
            )
            if call.semantic_operation_id == consumer_id.qualified_name
        )
        assert consumer.inputs["value"] == OutputInput(producer_output_id)
        assert consumer.payload_slot is not None
        payload_ids.append(consumer.payload_slot.id)

        state_value = (
            operations_of_type(plan, ApplyStateOperation, point_index=point.ordinal)[0]
            .targets[0]
            .value.root
        )
        assert isinstance(state_value, PayloadRef)
        assert state_value.payload_id == consumer.payload_slot.id

    assert len(set(payload_ids)) == 3
    repeated_payload_ids: list[str] = []
    for point in repeated.points:
        repeated_consumer = next(
            call
            for call in operations_of_type(
                repeated,
                ComputeOperation,
                point_index=point.ordinal,
            )
            if call.semantic_operation_id == consumer_id.qualified_name
        )
        assert repeated_consumer.payload_slot is not None
        repeated_payload_ids.append(repeated_consumer.payload_slot.id)
    assert payload_ids == repeated_payload_ids


@pytest.mark.parametrize(
    ("expression", "value_type"),
    (
        (
            literal_rows([{}]),
            Table(columns=(TableColumn("required", Scalar(String())),)),
        ),
        (
            literal_rows([{"declared": "ok", "extra": "no"}]),
            Table(columns=(TableColumn("declared", Scalar(String())),)),
        ),
        (
            literal_rows([{"id": "same"}, {"id": "same"}]),
            Table(
                columns=(TableColumn("id", Scalar(String())),),
                primary_key=("id",),
            ),
        ),
    ),
)
def test_point_domain_rejects_invalid_table_contract_before_binding(
    expression: RelationExpr,
    value_type: Table,
) -> None:
    with pytest.raises(RelationPlanVerificationError) as caught:
        table_value_expr(expression, expected_type=value_type)

    assert caught.value.code == "invalid_literal"


def test_compute_inputs_are_normalized_before_binding() -> None:
    node_id = _operation_id("normalize-frequency")
    point_type = Table(
        columns=(
            TableColumn(
                "frequency",
                Scalar(QuantityType(dimension="frequency")),
            ),
        ),
    )
    program = typed_program(
        id="normalized-compute-input",
        kind="compiler_test",
        point_domain=_point_domain(
            (
                (Quantity(value=5000.0, unit="MHz"),),
                (Quantity(value=5.0, unit="GHz"),),
            ),
            point_type,
        ),
        compute_nodes=(
            TypedComputeNode(
                id=node_id,
                implementation=_implementation(node_id, _quantity_value),
                inputs={
                    "frequency": ValueInput(
                        value=value_expr(
                            point_col("frequency"),
                            expected_type=Scalar(QuantityType(unit="GHz")),
                            bindings=_point_bindings(point_type),
                        ),
                    )
                },
                result=_output(node_id, Scalar(Float())),
            ),
        ),
    )

    plan = materialize_local_execution(
        link_program(program, build_config_environment(load_config()))
    )

    calls = [
        operations_of_type(plan, ComputeOperation, point_index=point.ordinal)[0]
        for point in plan.points
    ]
    assert [call.inputs["frequency"] for call in calls] == [
        BoundInput(Quantity(value=5.0, unit="GHz")),
        BoundInput(Quantity(value=5.0, unit="GHz")),
    ]


def test_compute_payload_input_rejects_mismatched_schema_before_binding() -> None:
    point_type = Table(
        columns=(TableColumn("payload", Scalar(Payload("source-payload"))),),
    )

    with pytest.raises(RelationPlanVerificationError) as caught:
        value_expr(
            point_col("payload"),
            expected_type=Scalar(Payload("expected-payload")),
            bindings=_point_bindings(point_type),
        )

    assert caught.value.code == "incompatible_result_type"


def test_compute_mapping_inputs_preserve_key_types_and_values() -> None:
    node_id = _operation_id("consume-mapping")
    point_type = Table(
        columns=(TableColumn("payload", Scalar(Payload("mapping"))),),
    )
    program = typed_program(
        id="mapping-fingerprint",
        kind="compiler_test",
        point_domain=_point_domain(
            (
                (
                    PayloadValue(
                        schema_id="mapping",
                        payload={1: "a", "1": "b"},
                    ),
                ),
                (
                    PayloadValue(
                        schema_id="mapping",
                        payload={1: "z", "1": "b"},
                    ),
                ),
            ),
            point_type,
        ),
        compute_nodes=(
            TypedComputeNode(
                id=node_id,
                implementation=_implementation(node_id, _mapping_size),
                inputs={
                    "payload": ValueInput(
                        value=value_expr(
                            point_col("payload"),
                            expected_type=Scalar(Payload("mapping")),
                            bindings=_point_bindings(point_type),
                        ),
                    )
                },
                result=_output(node_id, Scalar(Float())),
            ),
        ),
    )

    plan = materialize_local_execution(
        link_program(program, build_config_environment(load_config()))
    )

    assert (
        operations_of_type(plan, ComputeOperation, point_index=0)[0].inputs
        != operations_of_type(plan, ComputeOperation, point_index=1)[0].inputs
    )


def test_opaque_point_value_does_not_participate_in_logical_identity() -> None:
    program = typed_program(
        id="opaque-point",
        kind="compiler_test",
        point_domain=_point_domain(
            (
                (
                    PayloadValue(
                        schema_id="opaque",
                        payload=object(),
                    ),
                ),
            ),
            Table(
                columns=(TableColumn("payload", Scalar(Payload("opaque"))),),
            ),
        ),
    )

    plan = materialize_local_execution(
        link_program(program, build_config_environment(load_config()))
    )

    assert len(plan.points) == 1

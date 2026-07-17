from __future__ import annotations

from typing import Any, cast

import pytest

import scopecat.authoring as authoring
from scopecat.authoring._value_refs import (
    internal_value_ref_from_expression,
)
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.frontend.graph_validation import verify_assembly_graph
from scopecat.compiler.frontend.resolution import ResolvedExperiment
from scopecat.compiler.linking.linked import link_verified_program
from scopecat.compiler.linking.materialization import materialize_local_plan
from scopecat.compiler.relations.analysis import PlanNode
from scopecat.compiler.relations.evaluation import (
    EvalContext,
    ParameterRelationData,
)
from scopecat.compiler.relations.model import (
    ColumnScalarExpr,
    LiteralScalarExpr,
    grid,
    literal_rows,
    outer,
)
from scopecat.compiler.relations.uses import RelationUseId
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
    VerifiedRelationPlan,
)
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.model import (
    OperationId,
    OperationOutputSource,
    PlanExpressionSource,
    operation_result_id,
)
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
    SeriesValueExpr,
    TableValueExpr,
)
from scopecat.compiler.typed.point_domain import materialize_point_domain
from scopecat.compiler.typed.program import (
    ComputeEdge,
    ValueInput,
)
from scopecat.compiler.typed.state import (
    ForEachStateSpec,
    SetStateSpec,
    evaluate_state_spec,
)
from scopecat.execution.local.lowering import build_execution_program
from scopecat.execution.local.program import ActionStage
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import model_location
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_validation import ValueValidationError
from scopecat.planning.authoring import resolve_experiment
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity
from tests.testkit.authoring import load_config
from tests.testkit.bound_plan import bound_plan_contract
from tests.testkit.relation_plans import (
    each_state,
    materialize_scalar_value,
    materialize_series_value,
    materialize_table_value,
    state_field,
)


def test_action_lowers_as_a_distinct_point_effect() -> None:
    module = (
        authoring.module("test.action")
        .resource("source", requires=("set_frequency",))
        .action(
            "trigger",
            resource="source",
            capability="set_frequency",
            fields={"frequency": Quantity(value=5.0, unit="GHz")},
        )
        .build()
    )
    template = module.template("test.action", kind="action").build()
    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )

    assert len(resolved.experiment.actions) == 1
    bound = materialize_local_plan(
        link_verified_program(resolved.verified_program, resolved.environment)
    )
    assert not bound.problems
    assert len(bound.points[0].actions) == 1
    execution = build_execution_program(
        bound,
        instrument_order=tuple(
            action.resource_id.value for action in bound.points[0].actions
        ),
    )
    action_stage = next(
        stage for stage in execution.points[0].stages if isinstance(stage, ActionStage)
    )
    assert action_stage.operations[0].capability_id == "set_frequency"


def _echo_rows_offsets(*, rows: object, offsets: object) -> dict[str, object]:
    return {"rows": rows, "offsets": offsets}


def _echo_rows_items(*, rows: object, items: object) -> dict[str, object]:
    return {"rows": rows, "items": items}


def _echo_value_items_rows(
    *,
    value: object,
    items: object,
    rows: object,
) -> dict[str, object]:
    return {"value": value, "items": items, "rows": rows}


def _echo_program(*, program: object) -> dict[str, object]:
    return {"program": program}


def _echo_values(*, values: object) -> dict[str, object]:
    return {"values": values}


def _echo_label(*, label: object) -> dict[str, object]:
    return {"label": label}


def _empty_payload() -> dict[str, object]:
    return {}


def _empty_series() -> list[object]:
    return []


def _entity_scalar() -> authoring.ScalarType:
    return authoring.ScalarType(authoring.EntityType())


def _gate_table_type() -> authoring.TableType:
    return authoring.TableType(
        columns=(
            authoring.TableColumn("control", _entity_scalar()),
            authoring.TableColumn("target", _entity_scalar()),
        )
    )


def _state_rows_type() -> authoring.TableType:
    return authoring.TableType(
        columns=(
            authoring.TableColumn(
                "resource_id",
                authoring.ScalarType(authoring.StringType()),
            ),
            authoring.TableColumn(
                "base",
                authoring.ScalarType(authoring.FloatType()),
            ),
            authoring.TableColumn(
                "adjusted",
                authoring.ScalarType(authoring.FloatType()),
                required=False,
            ),
        )
    )


def _literal_table(
    rows: list[dict[str, Any]],
    **columns: authoring.ScalarType,
) -> authoring.ValueRef:
    return internal_value_ref_from_expression(
        literal_rows(rows),
        authoring.TableType(
            columns=tuple(
                authoring.TableColumn(column_id, value_type)
                for column_id, value_type in columns.items()
            )
        ),
    )


def _state_values(
    resolved: ResolvedExperiment,
) -> list[tuple[int, str, object]]:
    verified_program = resolved.verified_program
    points = [
        point.row
        for point in materialize_point_domain(
            verified_program.point_domain,
            resolved.parameters,
        ).points
    ]
    return [
        (record.point_index, str(record.resource_target), record.value)
        for point_index, point in enumerate(points)
        for record in evaluate_state_spec(
            resolved.experiment.state[0],
            point_index=point_index,
            ctx=EvalContext(
                params=resolved.parameters,
                row=point,
                point_row=point,
            ),
            relation_plan=verified_program.relation_plan,
            location=model_location("state", 0),
        )
    ]


def test_collections_cross_module_route_axis_and_compute_with_provenance() -> None:
    gate_table = _gate_table_type()
    offsets_type = authoring.SeriesType(authoring.ScalarType(authoring.FloatType()))
    gates = authoring.input("gates", gate_table)
    offsets = authoring.input("offsets", offsets_type)
    gate_entities = gates.entities("control", "target")
    prepare = authoring.compute(
        "prepare",
        fn=_echo_rows_offsets,
        inputs={"rows": gates, "offsets": offsets},
        output_type=authoring.ScalarType(authoring.PayloadType("prepared")),
    )
    child = (
        authoring.module("test.collections.child")
        .inputs(gates, offsets)
        .resource(
            "source",
            requires=("set_frequency",),
            for_entities=(gate_entities,),
        )
        .computes(prepare)
        .product(
            "signal",
            resource="source",
            axes=(authoring.entity_axis("qubit", gate_entities),),
        )
        .build()
    )
    gate_rows = authoring.input("gate_rows", gate_table)
    offset_values = authoring.input("offset_values", offsets_type)
    child_instance = child.instantiate(
        "collections-child",
        gates=gate_rows,
        offsets=offset_values,
    )
    parent = (
        authoring.module("test.collections.parent")
        .inputs(gate_rows, offset_values)
        .use(child_instance)
        .build()
    )
    template = (
        parent.template("test.collections", kind="collections")
        .experiment_id("collections")
        .record_product(child_instance.products.signal, record_id="signal")
        .build()
    )

    config = load_config()
    resolved = resolve_experiment(
        template.bind(
            gate_rows=(
                {"control": "q0", "target": "q0"},
                {"control": "q0", "target": "q0"},
            ),
            offset_values=(0.25, 0.5),
        ),
        config_profile=config,
    )
    experiment = resolved.experiment

    node = experiment.compute_nodes[0]
    rows = node.inputs["rows"]
    assert isinstance(rows, ValueInput)
    assert rows.origin_input_ids == ("gate_rows",)
    assert isinstance(rows.value, TableValueExpr)
    assert materialize_table_value(
        rows.value,
    ) == [
        {
            "control": EntityRef(id="q0"),
            "target": EntityRef(id="q0"),
        },
        {
            "control": EntityRef(id="q0"),
            "target": EntityRef(id="q0"),
        },
    ]

    offset_values = node.inputs["offsets"]
    assert isinstance(offset_values, ValueInput)
    assert offset_values.origin_input_ids == ("offset_values",)
    assert isinstance(offset_values.value, SeriesValueExpr)
    assert materialize_series_value(
        offset_values.value,
        EvalContext(),
    ) == [
        0.25,
        0.5,
    ]

    route_entities = experiment.route_intents[0].entity_uses[0].value
    assert isinstance(route_entities, SeriesValueExpr)
    assert materialize_series_value(
        route_entities,
        EvalContext(),
    ) == [EntityRef(id="q0")]

    axis = experiment.product_defs[0].axes[0]
    assert axis.size == 1
    assert axis.metadata == {
        "entity_kind": "logical_device",
        "entities": ({"id": "q0", "kind": "logical_device", "metadata": {}},),
    }

    preview = bound_plan_contract(
        experiment,
        resolved.parameters,
        config=config,
    )
    assert preview.points[0].routes[0].entity_ids == ("q0",)


def test_resource_entity_series_rejects_non_entity_members_during_authoring() -> None:
    items = authoring.input(
        "items",
        authoring.SeriesType(authoring.ScalarType(authoring.FloatType())),
    )
    with pytest.raises(TypeError, match="must be entity-shaped"):
        (
            authoring.module("test.invalid_resource_entities")
            .inputs(items)
            .resource(
                "source",
                requires=("set_frequency",),
                for_entities=(items,),
            )
        )

    table_source = cast(
        "Any",
        authoring.input("items", _gate_table_type()),
    )
    with pytest.raises(TypeError, match="must be entity-shaped"):
        (
            authoring.module("test.invalid_resource_entity_table")
            .inputs(table_source)
            .resource(
                "source",
                requires=("set_frequency",),
                for_entities=(table_source,),
            )
        )


def test_declared_shapes_disambiguate_empty_table_and_series_of_records() -> None:
    records = authoring.SeriesType(
        authoring.ScalarType(
            authoring.RecordType(
                fields=(
                    authoring.RecordField(
                        "label",
                        authoring.ScalarType(authoring.StringType()),
                    ),
                )
            )
        )
    )
    rows = authoring.input("rows", _gate_table_type())
    items = authoring.input("items", records)
    inspect = authoring.compute(
        "inspect",
        fn=_echo_rows_items,
        inputs={"rows": rows, "items": items},
        output_type=authoring.ScalarType(authoring.PayloadType("inspection")),
    )
    child = (
        authoring.module("test.collection_literals.child")
        .inputs(rows, items)
        .computes(inspect)
        .build()
    )
    parent = (
        authoring.module("test.collection_literals.parent")
        .use(
            child.instantiate(
                "literal-child",
                rows=(),
                items=({"label": "first"},),
            )
        )
        .build()
    )
    template = (
        parent.template("test.collection_literals", kind="collection_literals")
        .experiment_id("collection-literals")
        .build()
    )

    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )
    node = resolved.experiment.compute_nodes[0]

    rows = node.inputs["rows"]
    assert isinstance(rows, ValueInput)
    assert isinstance(rows.value, TableValueExpr)
    assert (
        materialize_table_value(
            rows.value,
        )
        == []
    )

    items = node.inputs["items"]
    assert isinstance(items, ValueInput)
    assert isinstance(items.value, SeriesValueExpr)
    assert materialize_series_value(
        items.value,
        EvalContext(),
    ) == [{"label": "first"}]


def test_same_name_inputs_pass_through_multiple_module_boundaries() -> None:
    scalar_type = authoring.ScalarType(authoring.FloatType())
    series_type = authoring.SeriesType(scalar_type)
    table_type = _state_rows_type()
    value = authoring.input("value", scalar_type)
    items = authoring.input("items", series_type)
    rows = authoring.input("rows", table_type)
    inspect = authoring.compute(
        "inspect",
        fn=_echo_value_items_rows,
        inputs={"value": value, "items": items, "rows": rows},
        output_type=authoring.ScalarType(authoring.PayloadType("inspection")),
    )
    leaf = (
        authoring.module("test.same_name.leaf")
        .inputs(value, items, rows)
        .computes(inspect)
        .build()
    )
    middle = (
        authoring.module("test.same_name.middle")
        .inputs(value, items, rows)
        .use(
            leaf.instantiate(
                "leaf",
                value=value,
                items=items,
                rows=rows,
            )
        )
        .build()
    )
    outer = (
        authoring.module("test.same_name.outer")
        .inputs(value, items, rows)
        .use(
            middle.instantiate(
                "middle",
                value=value,
                items=items,
                rows=rows,
            )
        )
        .build()
    )
    template = (
        outer.template("test.same_name", kind="same_name")
        .scan(authoring.point("value", scalar_type), (0.25, 0.5))
        .build()
    )

    resolved = resolve_experiment(
        template.bind(
            items=(1.0, 2.0),
            rows=({"resource_id": "source-a", "base": 1.0},),
        ),
        config_profile=load_config(),
    )
    node = resolved.experiment.compute_nodes[0]
    verified_program = resolved.verified_program
    points = [
        point.row
        for point in materialize_point_domain(
            verified_program.point_domain,
            resolved.parameters,
        ).points
    ]

    scalar = node.inputs["value"]
    assert isinstance(scalar, ValueInput)
    assert isinstance(scalar.value, ScalarValueExpr)
    assert (
        materialize_scalar_value(
            scalar.value,
            EvalContext(row=points[1], point_row=points[1]),
        )
        == 0.5
    )
    series = node.inputs["items"]
    assert isinstance(series, ValueInput)
    assert isinstance(series.value, SeriesValueExpr)
    assert materialize_series_value(
        series.value,
        EvalContext(),
    ) == [1.0, 2.0]
    table = node.inputs["rows"]
    assert isinstance(table, ValueInput)
    assert isinstance(table.value, TableValueExpr)
    assert materialize_table_value(
        table.value,
    ) == [{"resource_id": "source-a", "base": 1.0}]


def test_nested_module_requires_explicit_input_forwarding() -> None:
    value = authoring.input(
        "value",
        authoring.ScalarType(authoring.FloatType()),
    )
    child = authoring.module("test.nested_port.child").inputs(value).build()

    with pytest.raises(ValueError, match="must connect all inputs"):
        child.instantiate("child")

    outer_value = authoring.input("outer_value", value.value_type)
    root = (
        authoring.module("test.nested_port.root")
        .inputs(outer_value)
        .use(child.instantiate("child", value=outer_value))
        .build()
    )
    template = root.template("test.nested_port", kind="nested_port").build()

    resolve_experiment(
        template.bind(outer_value=1),
        config_profile=load_config(),
    )


def test_scan_points_are_coerced_by_same_named_scalar_input_type() -> None:
    scanned_value = authoring.input(
        "value",
        authoring.ScalarType(authoring.FloatType()),
    )
    module = authoring.module("test.scan_coercion").inputs(scanned_value).build()
    template = (
        module.template("test.scan_coercion", kind="scan_coercion")
        .scan(
            authoring.point(
                "value",
                authoring.ScalarType(authoring.FloatType()),
            ),
            (1,),
        )
        .build()
    )

    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )
    plan = materialize_local_plan(
        link_verified_program(resolved.verified_program, resolved.environment)
    )
    value = plan.points[0].row["value"]

    assert value == 1.0
    assert isinstance(value, float)


def test_scan_points_reject_same_named_scalar_input_constraint_violation() -> None:
    count = authoring.input(
        "count",
        authoring.ScalarType(authoring.IntType(minimum=1)),
    )
    module = authoring.module("test.scan_constraint").inputs(count).build()
    with pytest.raises(authoring.ValueValidationError) as error:
        (
            module.template("test.scan_constraint", kind="scan_constraint")
            .scan(
                authoring.point(
                    "count",
                    authoring.ScalarType(authoring.IntType(minimum=1)),
                ),
                (0,),
            )
            .build()
        )

    assert error.value.path == ("scan", "values", 0)
    assert error.value.reason == "value must be at least 1"


def test_module_invocation_rejects_collection_shape_mismatch() -> None:
    rows = authoring.input("rows", _gate_table_type())
    child = authoring.module("test.collection_shape.child").inputs(rows).build()
    items = authoring.input(
        "items",
        authoring.SeriesType(_entity_scalar()),
    )
    with pytest.raises(
        authoring.ValueValidationError,
        match=r"expected Table\{.*\}, got Series\[Scalar\[Entity\]\]",
    ):
        child.instantiate("collection-shape-child", rows=items)


def test_module_invocation_rejects_same_shape_atom_mismatch() -> None:
    entities = authoring.input(
        "entities",
        authoring.SeriesType(_entity_scalar()),
    )
    child = authoring.module("test.collection_atom.child").inputs(entities).build()
    numbers = authoring.input(
        "numbers",
        authoring.SeriesType(authoring.ScalarType(authoring.FloatType())),
    )
    with pytest.raises(
        authoring.ValueValidationError,
        match=r"expected Series\[Scalar\[Entity\]\], got Series\[Scalar\[Float\]\]",
    ):
        child.instantiate("collection-atom-child", entities=numbers)


def test_module_invocation_rejects_quantity_unit_and_table_schema_mismatch() -> None:
    frequency = authoring.input(
        "frequency",
        authoring.ScalarType(authoring.QuantityType(unit="GHz")),
    )
    quantity_child = (
        authoring.module("test.quantity_type.child").inputs(frequency).build()
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
    table_child = authoring.module("test.table_type.child").inputs(gates).build()
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
        authoring.module("test.compute_edge.child")
        .inputs(program)
        .computes(consume)
        .build()
    )
    middle_program = authoring.input("program", pulse)
    middle = (
        authoring.module("test.compute_edge.middle")
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
        authoring.module("test.compute_edge.parent")
        .computes(produce)
        .use(middle.instantiate("compute-middle", program=produce.output))
        .build()
    )

    assembly = elaborate_module(
        parent,
    )
    consumer = next(
        operation
        for operation in assembly.semantic_graph.operations
        if operation.id.local_id == "consume"
    )
    program_use = dict(consumer.inputs)["program"]
    program_definition = next(
        definition
        for definition in assembly.semantic_graph.value_defs
        if definition.id == program_use.value_id
    )
    assert isinstance(program_definition.source, OperationOutputSource)
    assert program_definition.source.operation_id == OperationId(
        SymbolId(local_id="produce")
    )
    resolved = resolve_experiment(
        parent.template("test.compute_edge", kind="compute_edge").build().bind(),
        config_profile=load_config(),
    )
    linked_consumer = next(
        node
        for node in resolved.experiment.compute_nodes
        if node.id.local_id == "consume"
    )
    linked_producer = next(
        node
        for node in resolved.experiment.compute_nodes
        if node.id.local_id == "produce"
    )
    program_edge = linked_consumer.inputs["program"]
    assert isinstance(program_edge, ComputeEdge)
    assert linked_producer.result.id == program_definition.id
    assert linked_producer.result.value_type == pulse
    assert program_edge.value_id == linked_producer.result.id
    assert program_edge.expected_type == linked_producer.result.value_type

    incompatible_program = authoring.input(
        "program",
        authoring.ScalarType(authoring.PayloadType("waveform")),
    )
    incompatible_child = (
        authoring.module("test.compute_edge.incompatible")
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


def test_series_compute_output_is_a_first_class_typed_value() -> None:
    float_series = authoring.SeriesType(authoring.ScalarType(authoring.FloatType()))
    values = authoring.input("values", float_series)
    consume = authoring.compute(
        "consume-series",
        fn=_echo_values,
        inputs={"values": values},
        output_type=authoring.ScalarType(authoring.PayloadType("consumed-series")),
    )
    child = (
        authoring.module("test.compute_series.child")
        .inputs(values)
        .computes(consume)
        .build()
    )
    produce = authoring.compute(
        "produce-series",
        fn=_empty_series,
        output_type=float_series,
    )
    parent = (
        authoring.module("test.compute_series.parent")
        .computes(produce)
        .use(child.instantiate("series-child", values=produce.output))
        .build()
    )

    resolved = resolve_experiment(
        parent.template("test.compute_series", kind="compute_series").build().bind(),
        config_profile=load_config(),
    )
    produce = next(
        node
        for node in resolved.experiment.compute_nodes
        if node.id.local_id == "produce-series"
    )
    consume = next(
        node
        for node in resolved.experiment.compute_nodes
        if node.id.local_id == "consume-series"
    )
    assert produce.result.value_type == float_series
    values_edge = consume.inputs["values"]
    assert isinstance(values_edge, ComputeEdge)
    assert values_edge.value_id == produce.result.id
    assert values_edge.expected_type == produce.result.value_type


def test_explicit_null_is_validated_as_a_value_not_treated_as_unbound() -> None:
    required_label = authoring.input(
        "label",
        authoring.ScalarType(authoring.StringType()),
    )
    required = (
        authoring.module("test.null.required")
        .inputs(required_label)
        .build()
        .template("test.null.required", kind="null")
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        resolve_experiment(
            required.bind(label=None),
            config_profile=load_config(),
        )
    assert error.value.problems[0].code == "module_input_type_mismatch"
    assert "value must not be null" in error.value.problems[0].message

    label = authoring.input(
        "label",
        authoring.ScalarType(
            authoring.StringType(),
            nullable=True,
        ),
    )
    inspect = authoring.compute(
        "inspect",
        fn=_echo_label,
        inputs={"label": label},
        output_type=authoring.ScalarType(authoring.PayloadType("inspection")),
    )
    nullable = (
        authoring.module("test.null.nullable")
        .inputs(label)
        .computes(inspect)
        .build()
        .template("test.null.nullable", kind="null")
        .build()
    )
    resolved = resolve_experiment(
        nullable.bind(label=None),
        config_profile=load_config(),
    )

    value_input = resolved.experiment.compute_nodes[0].inputs["label"]
    assert isinstance(value_input, ValueInput)
    value = value_input.value
    assert isinstance(value, ScalarValueExpr)
    assert isinstance(value.plan.root, LiteralScalarExpr)
    assert value.plan.root.value is None


def test_table_input_drives_child_state_with_outer_scanned_input() -> None:
    state_rows = _state_rows_type()
    rows = authoring.input("rows", state_rows)
    bias = authoring.input(
        "bias",
        authoring.ScalarType(authoring.FloatType()),
    )
    child = (
        authoring.module("test.collection_state.child")
        .inputs(rows, bias)
        .state_each(
            rows,
            resource=lambda row: row["resource_id"],
            capability="set_offset",
            field="offset",
            value=lambda row: row["base"] + bias,
        )
        .build()
    )
    outer_rows = authoring.input("state_rows", state_rows)
    point_bias = authoring.input(
        "point_bias",
        authoring.ScalarType(authoring.FloatType()),
    )
    parent = (
        authoring.module("test.collection_state.parent")
        .inputs(outer_rows, point_bias)
        .use(
            child.instantiate(
                "state-child",
                rows=outer_rows,
                bias=point_bias,
            )
        )
        .build()
    )
    template = (
        parent.template("test.collection_state", kind="collection_state")
        .experiment_id("collection-state")
        .scan(
            authoring.point(
                "point_bias",
                authoring.ScalarType(authoring.FloatType()),
            ),
            (0.25, 0.5),
        )
        .build()
    )

    resolved = resolve_experiment(
        template.bind(
            state_rows=(
                {"resource_id": "source-a", "base": 1.0},
                {"resource_id": "source-b", "base": 2.0},
            )
        ),
        config_profile=load_config(),
    )
    assert _state_values(resolved) == [
        (0, "source-a", 1.25),
        (0, "source-b", 2.25),
        (1, "source-a", 1.5),
        (1, "source-b", 2.5),
    ]


def test_state_each_rejects_a_row_value_captured_by_another_binder() -> None:
    captured: list[authoring.ValueRef] = []
    row_type = {
        "resource_id": authoring.ScalarType(authoring.StringType()),
        "base": authoring.ScalarType(authoring.FloatType()),
    }
    first = _literal_table(
        [{"resource_id": "source-a", "base": 1.0}],
        **row_type,
    )
    second = _literal_table(
        [{"resource_id": "source-b", "base": 2.0}],
        **row_type,
    )

    def capture_resource(row: authoring.TableRow) -> authoring.ValueRef:
        resource = row["resource_id"]
        captured.append(resource)
        return resource

    module = (
        authoring.module("test.collection_state.foreign-row-capture")
        .state_each(
            first,
            resource=capture_resource,
            capability="set_offset",
            field="offset",
            value=lambda row: row["base"],
        )
        .state_each(
            second,
            resource=lambda _row: captured[0],
            capability="set_offset",
            field="offset",
            value=lambda row: row["base"],
        )
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        verify_assembly_graph(elaborate_module(module))

    assert "semantic_row_region_body_visibility_invalid" in {
        problem.code for problem in error.value.problems
    }


@pytest.mark.parametrize(
    ("resource", "value", "route_entities", "code"),
    [
        (1.0, 1.0, (), "semantic_row_region_resource_type_invalid"),
        ("source-a", "bad", (), "semantic_row_region_value_type_invalid"),
        (
            "source-a",
            10**400,
            (),
            "semantic_row_region_value_type_invalid",
        ),
        (
            "source-a",
            1.0,
            ((1.0, 2.0),),
            "semantic_row_region_route_type_invalid",
        ),
        (
            "source-a",
            1.0,
            ((),),
            "semantic_row_region_route_type_invalid",
        ),
        (
            "source-a",
            1.0,
            (("",),),
            "semantic_row_region_route_type_invalid",
        ),
    ],
)
def test_state_each_rejects_body_values_outside_consumer_contracts(
    resource: Any,
    value: Any,
    route_entities: tuple[Any, ...],
    code: str,
) -> None:
    module = (
        authoring.module("test.collection_state.invalid-body")
        .state_each(
            _literal_table([{}]),
            resource=resource,
            capability="set_offset",
            field="offset",
            value=value,
            route_entities=route_entities,
        )
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        verify_assembly_graph(elaborate_module(module))

    assert {problem.code for problem in error.value.problems} == {code}


def test_module_instances_alpha_rename_state_row_scopes() -> None:
    rows = _literal_table(
        [{"resource_id": "source-a", "base": 1.0}],
        resource_id=authoring.ScalarType(authoring.StringType()),
        base=authoring.ScalarType(authoring.FloatType()),
    )
    child = (
        authoring.module("test.collection_state.alpha-child")
        .state_each(
            rows,
            resource=lambda row: row["resource_id"],
            capability="set_offset",
            field="offset",
            value=lambda row: row["base"],
        )
        .build()
    )
    root = (
        authoring.module("test.collection_state.alpha-root")
        .use(child.instantiate("left"), child.instantiate("right"))
        .build()
    )

    assembly = elaborate_module(root)
    regions = assembly.semantic_graph.row_regions
    definitions = {
        definition.id: definition for definition in assembly.semantic_graph.value_defs
    }

    assert len(regions) == 2
    qualified_scopes = tuple(
        region.row_argument.id.qualified_name for region in regions
    )
    assert len(set(qualified_scopes)) == 2
    assert qualified_scopes[0].startswith("left/state_row_")
    assert qualified_scopes[1].startswith("right/state_row_")
    for region in regions:
        assert region.resource is not None
        definition = definitions[region.resource.value_id]
        assert isinstance(definition.source, PlanExpressionSource)
        expression = definition.source.expression
        assert isinstance(expression, ColumnScalarExpr)
        assert expression.row_scope_id == region.row_argument.id
        assert definition.owner_region_id == region.id


def test_state_regions_and_lowered_state_preserve_authored_order() -> None:
    rows = _literal_table([{}])
    module = (
        authoring.module("test.collection_state.order")
        .state_each(
            rows,
            resource="source-a",
            capability="set_offset",
            field="first",
            value=1.0,
        )
        .state_each(
            rows,
            resource="source-b",
            capability="set_offset",
            field="second",
            value=2.0,
        )
        .build()
    )
    assembly = elaborate_module(module)

    assert [region.field_path for region in assembly.semantic_graph.row_regions] == [
        "first",
        "second",
    ]

    template = module.template(
        "test.collection_state.order",
        kind="collection_state",
    ).build()
    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )
    children = [
        state.state[0]
        for state in resolved.experiment.state
        if isinstance(state, ForEachStateSpec)
    ]
    assert [
        state.field_path for state in children if isinstance(state, SetStateSpec)
    ] == ["first", "second"]


def test_state_route_entities_use_durable_scalar_and_series_shapes() -> None:
    entity_series = authoring.SeriesType(_entity_scalar())
    qubits = authoring.input("qubits", entity_series)
    module = (
        authoring.module("test.collection_state.routes")
        .inputs(qubits)
        .state_each(
            _literal_table(
                [{"resource_id": "source-0"}],
                resource_id=authoring.ScalarType(authoring.StringType()),
            ),
            resource=lambda row: row["resource_id"],
            capability="set_frequency",
            field="frequency",
            value=1.0,
            route_entities=(EntityRef(id="q0"), qubits),
        )
        .build()
    )
    template = module.template(
        "test.collection_state.routes",
        kind="collection_state",
    ).build()
    resolved = resolve_experiment(
        template.bind(qubits=("q0",)),
        config_profile=load_config(),
    )

    state = resolved.experiment.state[0]
    assert isinstance(state, ForEachStateSpec)
    child = state.state[0]
    assert isinstance(child, SetStateSpec)
    route_entities = child.route_entity_uses
    assert isinstance(route_entities[0].value, ScalarValueExpr)
    assert isinstance(route_entities[1].value, SeriesValueExpr)

    verified_program = resolved.verified_program
    records = evaluate_state_spec(
        state,
        point_index=0,
        ctx=EvalContext(params=ParameterRelationData(), row={}),
        relation_plan=verified_program.relation_plan,
        location=model_location("state", 0),
    )
    assert records[0].route_entities == (EntityRef(id="q0"),)


def test_nested_state_preserves_an_empty_parent_row_as_outer_scope() -> None:
    leaf = state_field(
        "source-a",
        capability_id="set_offset",
        field_path="offset",
        value=1.0,
    )
    nested = each_state(
        grid(observed=outer("ambient")),
        leaf,
        bindings=RelationTypeBindings(
            outer_row=RowType(
                columns=(
                    authoring.TableColumn(
                        "ambient",
                        authoring.ScalarType(authoring.FloatType()),
                    ),
                )
            )
        ),
    )
    state = each_state(literal_rows([{}]), nested)
    child = state.state[0]
    assert isinstance(child, ForEachStateSpec)
    verified_plans: dict[
        RelationUseId,
        VerifiedRelationPlan[PlanNode],
    ] = {
        state.relation_use.id: state.relation_use.value.plan,
        child.relation_use.id: child.relation_use.value.plan,
    }

    with pytest.raises(
        ValueValidationError,
        match=r"rows\.outer.*missing required columns: ambient",
    ):
        evaluate_state_spec(
            state,
            point_index=0,
            ctx=EvalContext(outer_row={"ambient": 1.0}),
            relation_plan=verified_plans.__getitem__,
            location=model_location("state", 0),
        )


def test_state_each_preserves_compute_result_refs_across_module_inputs() -> None:
    resource_id = authoring.input(
        "resource_id",
        authoring.ScalarType(authoring.StringType()),
    )
    build_program = authoring.compute(
        "build-program",
        fn=_empty_payload,
        output_type=authoring.ScalarType(authoring.PayloadType("pulse_program")),
    )
    child = (
        authoring.module("test.collection_state.compute_payload_child")
        .inputs(resource_id)
        .computes(build_program)
        .state_each(
            _literal_table(
                [{"slot": 0}],
                slot=authoring.ScalarType(authoring.IntType()),
            ),
            resource=resource_id,
            capability="play_waveforms",
            field="program",
            value=build_program.output,
        )
        .build()
    )
    parent = (
        authoring.module("test.collection_state.compute_payload_parent")
        .use(child.instantiate("payload-child", resource_id="source-a"))
        .build()
    )
    template = parent.template(
        "test.collection_state.compute_payload",
        kind="collection_state",
    ).build()

    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )

    state = resolved.experiment.state[0]
    assert isinstance(state, ForEachStateSpec)
    child = state.state[0]
    assert isinstance(child, SetStateSpec)
    assert child.value_use == ComputeResultRef(
        value_id=operation_result_id(
            OperationId(
                SymbolId(
                    scope=("payload-child",),
                    local_id="build-program",
                )
            )
        )
    )


def test_state_each_resolves_inputs_nested_inside_a_relation() -> None:
    state_rows = _state_rows_type()
    rows = authoring.input("rows", state_rows)
    child = (
        authoring.module("test.collection_state.relation_child")
        .inputs(rows)
        .state_each(
            rows,
            resource=lambda row: row["resource_id"],
            capability="set_offset",
            field="offset",
            value=lambda row: row["adjusted"],
        )
        .build()
    )
    bias = authoring.input(
        "bias",
        authoring.ScalarType(authoring.FloatType()),
    )
    parent = (
        authoring.module("test.collection_state.relation_parent")
        .inputs(bias)
        .use(
            child.instantiate(
                "relation-child",
                rows=_literal_table(
                    [{"resource_id": "source-a", "base": 1.0}],
                    resource_id=authoring.ScalarType(authoring.StringType()),
                    base=authoring.ScalarType(authoring.FloatType()),
                ).with_columns(lambda row: {"adjusted": row["base"] + bias}),
            )
        )
        .build()
    )
    template = (
        parent.template("test.collection_state.relation", kind="collection_state")
        .scan(
            authoring.point(
                "bias",
                authoring.ScalarType(authoring.FloatType()),
            ),
            (0.25, 0.5),
        )
        .build()
    )

    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )

    assert _state_values(resolved) == [
        (0, "source-a", 1.25),
        (1, "source-a", 1.5),
    ]


def test_state_each_preserves_outer_scope_across_two_module_boundaries() -> None:
    state_rows = _state_rows_type()
    writer_rows = authoring.input(
        "rows",
        authoring.TableType(
            columns=tuple(
                authoring.TableColumn(column.id, column.value_type)
                for column in state_rows.columns
            )
        ),
    )
    writer = (
        authoring.module("test.collection_state.writer")
        .inputs(writer_rows)
        .state_each(
            writer_rows,
            resource=lambda row: row["resource_id"],
            capability="set_offset",
            field="offset",
            value=lambda row: row["adjusted"],
        )
        .build()
    )
    middle_rows = authoring.input("middle_rows", state_rows)
    middle_bias = authoring.input(
        "bias",
        authoring.ScalarType(authoring.FloatType()),
    )
    middle = (
        authoring.module("test.collection_state.middle")
        .inputs(middle_rows, middle_bias)
        .use(
            writer.instantiate(
                "writer",
                rows=middle_rows.with_columns(
                    lambda row: {"adjusted": row["base"] + middle_bias}
                ),
            )
        )
        .build()
    )
    outer_rows = authoring.input("state_rows", state_rows)
    outer_bias = authoring.input(
        "point_bias",
        authoring.ScalarType(authoring.FloatType()),
    )
    parent = (
        authoring.module("test.collection_state.outer")
        .inputs(outer_rows, outer_bias)
        .use(
            middle.instantiate(
                "middle",
                middle_rows=outer_rows,
                bias=outer_bias,
            )
        )
        .build()
    )
    template = (
        parent.template("test.collection_state.nested", kind="collection_state")
        .scan(
            authoring.point(
                "point_bias",
                authoring.ScalarType(authoring.FloatType()),
            ),
            (0.25, 0.5),
        )
        .build()
    )

    resolved = resolve_experiment(
        template.bind(
            state_rows=({"resource_id": "source-a", "base": 1.0},),
        ),
        config_profile=load_config(),
    )

    assert _state_values(resolved) == [
        (0, "source-a", 1.25),
        (1, "source-a", 1.5),
    ]


def test_state_each_rejects_unguarded_optional_column_access() -> None:
    rows_type = _state_rows_type()
    rows = authoring.input("rows", rows_type)
    module = (
        authoring.module("test.collection_state.optional_column")
        .inputs(rows)
        .state_each(
            rows,
            resource=lambda row: row["resource_id"],
            capability="set_offset",
            field="offset",
            value=lambda row: row["adjusted"],
        )
        .build()
    )
    template = module.template(
        "test.collection_state.optional_column",
        kind="collection_state",
    ).build()

    with pytest.raises(CheckFailed) as caught:
        resolve_experiment(
            template.bind(
                rows=({"resource_id": "source-a", "base": 1.0},),
            ),
            config_profile=load_config(),
        )

    assert caught.value.problems[0].code == "relation_plan_optional_column_access"


def test_state_each_treats_resource_string_as_a_fixed_resource_id() -> None:
    module = (
        authoring.module("test.collection_state.fixed_resource")
        .state_each(
            _literal_table(
                [{"value": 1.0}],
                value=authoring.ScalarType(authoring.FloatType()),
            ),
            resource="fixed-source",
            capability="set_offset",
            field="offset",
            value=lambda row: row["value"],
        )
        .build()
    )
    template = module.template(
        "test.collection_state.fixed_resource",
        kind="collection_state",
    ).build()

    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )

    assert _state_values(resolved) == [(0, "fixed-source", 1.0)]


def test_state_each_validates_resource_port_capability() -> None:
    module = (
        authoring.module("test.collection_state.capability")
        .resource("source", requires=("set_frequency",))
        .state_each(
            _literal_table(
                [{"value": 1.0}],
                value=authoring.ScalarType(authoring.FloatType()),
            ),
            resource_port="source",
            capability="set_power",
            field="value",
            value=lambda row: row["value"],
        )
        .build()
    )
    template = module.template(
        "test.collection_state.capability",
        kind="collection_state",
    ).build()

    with pytest.raises(CheckFailed) as error:
        resolve_experiment(
            template.bind(),
            config_profile=load_config(),
        )

    assert error.value.problems[0].code == ("module_resource_port_capability_missing")

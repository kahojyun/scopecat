from __future__ import annotations

from typing import Any, cast

import pytest

import scopecat.authoring as authoring
from scopecat.authoring._value_refs import (
    internal_value_ref_from_expression,
)
from scopecat.authoring.scans import axis
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.frontend.graph_validation import verify_assembly_graph
from scopecat.compiler.frontend.resolution import ResolvedExperiment
from scopecat.compiler.linking.linked import link_verified_program
from scopecat.compiler.relations.evaluation import (
    EvalContext,
    ParameterRelationData,
)
from scopecat.compiler.relations.model import (
    ColumnScalarExpr,
    LiteralScalarExpr,
    literal_rows,
)
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.model import (
    ActionEffectRef,
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
from scopecat.compiler.typed.action import ActionSpec
from scopecat.compiler.typed.point_domain import materialize_point_domain
from scopecat.compiler.typed.program import (
    ComputeEdge,
    TypedDomainExecution,
    ValueInput,
    core_state,
)
from scopecat.compiler.typed.state import (
    ForEachStateSpec,
    SetStateSpec,
    evaluate_state_spec,
)
from scopecat.execution.local.program import (
    CollectOperation,
    InstrumentActionOperation,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import model_location
from scopecat.kernel.symbols import SymbolId
from scopecat.planning.authoring import resolve_experiment
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity
from tests.testkit.authoring import load_config, template_fixture
from tests.testkit.local_materialization import (
    materialize_local_execution,
    operations_of_type,
)
from tests.testkit.materialized_effects import materialized_effects_contract
from tests.testkit.relation_plans import (
    materialize_scalar_value,
    materialize_series_value,
    materialize_table_value,
)


def test_action_lowers_as_a_distinct_point_effect() -> None:
    module = (
        authoring.module_body(id="test.action")
        .resource("source", requires=("set_frequency",))
        .action(
            "trigger",
            resource="source",
            capability="set_frequency",
            fields={"frequency": Quantity(value=5.0, unit="GHz")},
        )
        .build()
    )
    template = template_fixture(module, id="test.action", kind="action")
    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )

    bound = materialize_local_execution(
        link_verified_program(resolved.verified_program, resolved.environment)
    )
    [action] = operations_of_type(bound, InstrumentActionOperation, point_index=0)
    assert action.capability_id == "set_frequency"


def test_module_procedure_preserves_effect_order_across_effect_kinds() -> None:
    program = authoring.domain_program(
        "pulse",
        dialect_id="test",
        dialect_version="1",
        body=object(),
    )
    module = (
        authoring.module_body(id="test.effect-order")
        .resource("source", requires=("set_frequency",))
        .action(
            "arm",
            resource="source",
            capability="set_frequency",
        )
        .domain(authoring.domain_execution(program))
        .bind_field(
            "source",
            capability="set_frequency",
            field="frequency",
            value=Quantity(value=5.0, unit="GHz"),
        )
        .action(
            "trigger",
            resource="source",
            capability="set_frequency",
        )
        .build()
    )
    resolved = resolve_experiment(
        template_fixture(
            module,
            id="test.effect-order",
            kind="effect-order",
        ).bind(),
        config_profile=load_config(),
    )

    assert tuple(type(effect) for effect in resolved.experiment.effects) == (
        ActionSpec,
        TypedDomainExecution,
        SetStateSpec,
        ActionSpec,
    )


def test_child_procedure_is_inlined_at_its_module_occurrence() -> None:
    child = (
        authoring.module_body(id="test.effect-order.child")
        .resource("source", requires=("set_frequency",))
        .action("child", resource="source", capability="set_frequency")
        .build()
        .instantiate("nested")
    )
    parent = (
        authoring.module_body(id="test.effect-order.parent")
        .resource("source", requires=("set_frequency",))
        .action("before", resource="source", capability="set_frequency")
        .use(child)
        .action("after", resource="source", capability="set_frequency")
        .build()
    )

    assembly = elaborate_module(parent)

    assert tuple(
        effect.id.qualified_name
        for effect in assembly.effect_order
        if isinstance(effect, ActionEffectRef)
    ) == ("actions/before", "nested/actions/child", "actions/after")


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
            core_state(resolved.experiment)[0],
            point_index=point_index,
            ctx=EvalContext(
                params=resolved.parameters,
                point_row=point,
            ),
            relation_plan=verified_program.relation_plan,
            location=model_location("state", 0),
        )
    ]


def test_collections_cross_module_resource_entity_axis_with_provenance() -> None:
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
        authoring.module_body(id="test.collections.child")
        .inputs(gates, offsets)
        .resource(
            "source",
            requires=("set_frequency", "scalar_signal"),
            for_entities=(gate_entities,),
        )
        .computes(prepare)
        .product(
            "signal",
            axes=(authoring.entity_axis("qubit", gate_entities),),
        )
        .acquire(
            "read-signal",
            "signal",
            resource="source",
            capability="scalar_signal",
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
        authoring.module_body(id="test.collections.parent")
        .inputs(gate_rows, offset_values)
        .use(child_instance)
        .build()
    )
    template = template_fixture(
        parent,
        id="test.collections",
        kind="collections",
        records=(
            authoring.record_product(
                child_instance.products.signal,
                record_id="signal",
            ),
        ),
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
        EvalContext(),
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

    target_entities = experiment.resource_requirements[0].entity_uses[0].value
    assert isinstance(target_entities, SeriesValueExpr)
    assert materialize_series_value(
        target_entities,
        EvalContext(),
    ) == [EntityRef(id="q0")]

    axis = experiment.product_defs[0].axes[0]
    assert axis.size == 1
    assert axis.metadata == {
        "entity_kind": "logical_device",
        "entities": ({"id": "q0", "kind": "logical_device", "metadata": {}},),
    }

    preview = materialized_effects_contract(
        experiment,
        resolved.parameters,
        config=config,
    )
    [operation] = operations_of_type(preview, CollectOperation, point_index=0)
    [request] = operation.command.requests
    assert request.entity_ids == ["q0"]


def test_resource_entity_series_rejects_non_entity_members_during_authoring() -> None:
    items = authoring.input(
        "items",
        authoring.SeriesType(authoring.ScalarType(authoring.FloatType())),
    )
    with pytest.raises(TypeError, match="must be entity-shaped"):
        (
            authoring.module_body(id="test.invalid_resource_entities")
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
            authoring.module_body(id="test.invalid_resource_entity_table")
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
        authoring.module_body(id="test.collection_literals.child")
        .inputs(rows, items)
        .computes(inspect)
        .build()
    )
    parent = (
        authoring.module_body(id="test.collection_literals.parent")
        .use(
            child.instantiate(
                "literal-child",
                rows=(),
                items=({"label": "first"},),
            )
        )
        .build()
    )
    template = template_fixture(
        parent,
        id="test.collection_literals",
        kind="collection_literals",
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
            EvalContext(),
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
        authoring.module_body(id="test.same_name.leaf")
        .inputs(value, items, rows)
        .computes(inspect)
        .build()
    )
    middle = (
        authoring.module_body(id="test.same_name.middle")
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
        authoring.module_body(id="test.same_name.outer")
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
    template = template_fixture(
        outer,
        id="test.same_name",
        kind="same_name",
        scans=(
            axis(
                authoring.coordinate("value", scalar_type),
                (0.25, 0.5),
            ),
        ),
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
            EvalContext(point_row=points[1]),
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
        EvalContext(),
    ) == [{"resource_id": "source-a", "base": 1.0}]


def test_nested_module_requires_explicit_input_forwarding() -> None:
    value = authoring.input(
        "value",
        authoring.ScalarType(authoring.FloatType()),
    )
    child = authoring.module_body(id="test.nested_port.child").inputs(value).build()

    with pytest.raises(ValueError, match="must connect all inputs"):
        child.instantiate("child")

    outer_value = authoring.input("outer_value", value.value_type)
    root = (
        authoring.module_body(id="test.nested_port.root")
        .inputs(outer_value)
        .use(child.instantiate("child", value=outer_value))
        .build()
    )
    template = template_fixture(
        root,
        id="test.nested_port",
        kind="nested_port",
    )

    resolve_experiment(
        template.bind(outer_value=1),
        config_profile=load_config(),
    )


def test_scan_points_are_coerced_by_same_named_scalar_input_type() -> None:
    scanned_value = authoring.input(
        "value",
        authoring.ScalarType(authoring.FloatType()),
    )
    module = (
        authoring.module_body(id="test.scan_coercion").inputs(scanned_value).build()
    )
    template = template_fixture(
        module,
        id="test.scan_coercion",
        kind="scan_coercion",
        scans=(
            axis(
                authoring.coordinate(
                    "value",
                    authoring.ScalarType(authoring.FloatType()),
                ),
                (1,),
            ),
        ),
    )

    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )
    plan = materialize_local_execution(
        link_verified_program(resolved.verified_program, resolved.environment)
    )
    value = plan.points[0].coordinates["value"]

    assert value == 1.0
    assert isinstance(value, float)


def test_scan_points_reject_same_named_scalar_input_constraint_violation() -> None:
    count = authoring.input(
        "count",
        authoring.ScalarType(authoring.IntType(minimum=1)),
    )
    module = authoring.module_body(id="test.scan_constraint").inputs(count).build()
    with pytest.raises(authoring.ValueValidationError) as error:
        template_fixture(
            module,
            id="test.scan_constraint",
            kind="scan_constraint",
            scans=(
                axis(
                    authoring.coordinate(
                        "count",
                        authoring.ScalarType(authoring.IntType(minimum=1)),
                    ),
                    (0,),
                ),
            ),
        )

    assert error.value.path == ("scan", "values", 0)
    assert error.value.reason == "value must be at least 1"


def test_module_invocation_rejects_collection_shape_mismatch() -> None:
    rows = authoring.input("rows", _gate_table_type())
    child = authoring.module_body(id="test.collection_shape.child").inputs(rows).build()
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
    child = (
        authoring.module_body(id="test.collection_atom.child").inputs(entities).build()
    )
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
        authoring.module_body(id="test.quantity_type.child").inputs(frequency).build()
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
    table_child = (
        authoring.module_body(id="test.table_type.child").inputs(gates).build()
    )
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
        authoring.module_body(id="test.compute_edge.child")
        .inputs(program)
        .computes(consume)
        .build()
    )
    middle_program = authoring.input("program", pulse)
    middle = (
        authoring.module_body(id="test.compute_edge.middle")
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
        authoring.module_body(id="test.compute_edge.parent")
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
        template_fixture(
            parent,
            id="test.compute_edge",
            kind="compute_edge",
        ).bind(),
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
        authoring.module_body(id="test.compute_edge.incompatible")
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
        authoring.module_body(id="test.compute_series.child")
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
        authoring.module_body(id="test.compute_series.parent")
        .computes(produce)
        .use(child.instantiate("series-child", values=produce.output))
        .build()
    )

    resolved = resolve_experiment(
        template_fixture(
            parent,
            id="test.compute_series",
            kind="compute_series",
        ).bind(),
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
    required = template_fixture(
        authoring.module_body(id="test.null.required").inputs(required_label).build(),
        id="test.null.required",
        kind="null",
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
    nullable = template_fixture(
        authoring.module_body(id="test.null.nullable")
        .inputs(label)
        .computes(inspect)
        .build(),
        id="test.null.nullable",
        kind="null",
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
        authoring.module_body(id="test.collection_state.child")
        .inputs(rows, bias)
        .resource("source", requires=("set_offset",))
        .state_each(
            rows,
            resource_port="source",
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
        authoring.module_body(id="test.collection_state.parent")
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
    template = template_fixture(
        parent,
        id="test.collection_state",
        kind="collection_state",
        scans=(
            axis(
                authoring.coordinate(
                    "point_bias",
                    authoring.ScalarType(authoring.FloatType()),
                ),
                (0.25, 0.5),
            ),
        ),
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
        (0, "state-child/source", 1.25),
        (0, "state-child/source", 2.25),
        (1, "state-child/source", 1.5),
        (1, "state-child/source", 2.5),
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

    def capture_value(row: authoring.TableRow) -> authoring.ValueRef:
        value = row["base"]
        captured.append(value)
        return value

    module = (
        authoring.module_body(id="test.collection_state.foreign-row-capture")
        .resource("source", requires=("set_offset",))
        .state_each(
            first,
            resource_port="source",
            capability="set_offset",
            field="offset",
            value=capture_value,
        )
        .state_each(
            second,
            resource_port="source",
            capability="set_offset",
            field="offset",
            value=lambda _row: captured[0],
        )
        .build()
    )

    with pytest.raises(CheckFailed) as error:
        verify_assembly_graph(elaborate_module(module))

    assert "semantic_row_region_body_visibility_invalid" in {
        problem.code for problem in error.value.problems
    }


@pytest.mark.parametrize(
    ("value", "target_entities", "code"),
    [
        ("bad", (), "semantic_row_region_value_type_invalid"),
        (
            10**400,
            (),
            "semantic_row_region_value_type_invalid",
        ),
        (
            1.0,
            ((1.0, 2.0),),
            "semantic_row_region_target_type_invalid",
        ),
        (
            1.0,
            ((),),
            "semantic_row_region_target_type_invalid",
        ),
        (
            1.0,
            (("",),),
            "semantic_row_region_target_type_invalid",
        ),
    ],
)
def test_state_each_rejects_body_values_outside_consumer_contracts(
    value: Any,
    target_entities: tuple[Any, ...],
    code: str,
) -> None:
    module = (
        authoring.module_body(id="test.collection_state.invalid-body")
        .resource("source", requires=("set_offset",))
        .state_each(
            _literal_table([{}]),
            resource_port="source",
            capability="set_offset",
            field="offset",
            value=value,
            target_entities=target_entities,
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
        authoring.module_body(id="test.collection_state.alpha-child")
        .resource("source", requires=("set_offset",))
        .state_each(
            rows,
            resource_port="source",
            capability="set_offset",
            field="offset",
            value=lambda row: row["base"],
        )
        .build()
    )
    root = (
        authoring.module_body(id="test.collection_state.alpha-root")
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
        definition = definitions[region.value.value_id]
        assert isinstance(definition.source, PlanExpressionSource)
        expression = definition.source.expression
        assert isinstance(expression, ColumnScalarExpr)
        assert expression.row_scope_id == region.row_argument.id
        assert definition.owner_region_id == region.id


def test_state_regions_and_lowered_state_preserve_authored_order() -> None:
    rows = _literal_table([{}])
    module = (
        authoring.module_body(id="test.collection_state.order")
        .resource("source", requires=("set_offset",))
        .state_each(
            rows,
            resource_port="source",
            capability="set_offset",
            field="first",
            value=1.0,
        )
        .state_each(
            rows,
            resource_port="source",
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

    template = template_fixture(
        module,
        id="test.collection_state.order",
        kind="collection_state",
    )
    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )
    children = [
        state.state[0]
        for state in core_state(resolved.experiment)
        if isinstance(state, ForEachStateSpec)
    ]
    assert [
        state.field_path for state in children if isinstance(state, SetStateSpec)
    ] == ["first", "second"]


def test_state_target_entities_use_durable_scalar_and_series_shapes() -> None:
    entity_series = authoring.SeriesType(_entity_scalar())
    qubits = authoring.input("qubits", entity_series)
    module = (
        authoring.module_body(id="test.collection_state.targets")
        .inputs(qubits)
        .resource("source", requires=("set_frequency",))
        .state_each(
            _literal_table(
                [{"resource_id": "source-0"}],
                resource_id=authoring.ScalarType(authoring.StringType()),
            ),
            resource_port="source",
            capability="set_frequency",
            field="frequency",
            value=1.0,
            target_entities=(EntityRef(id="q0"), qubits),
        )
        .build()
    )
    template = template_fixture(
        module,
        id="test.collection_state.targets",
        kind="collection_state",
    )
    resolved = resolve_experiment(
        template.bind(qubits=("q0",)),
        config_profile=load_config(),
    )

    state = core_state(resolved.experiment)[0]
    assert isinstance(state, ForEachStateSpec)
    child = state.state[0]
    assert isinstance(child, SetStateSpec)
    target_entities = child.target_entity_uses
    assert isinstance(target_entities[0].value, ScalarValueExpr)
    assert isinstance(target_entities[1].value, SeriesValueExpr)

    verified_program = resolved.verified_program
    records = evaluate_state_spec(
        state,
        point_index=0,
        ctx=EvalContext(params=ParameterRelationData()),
        relation_plan=verified_program.relation_plan,
        location=model_location("state", 0),
    )
    assert records[0].target_entities == (EntityRef(id="q0"),)


def test_state_each_preserves_compute_result_refs_across_module_inputs() -> None:
    build_program = authoring.compute(
        "build-program",
        fn=_empty_payload,
        output_type=authoring.ScalarType(authoring.PayloadType("pulse_program")),
    )
    child = (
        authoring.module_body(id="test.collection_state.compute_payload_child")
        .resource("source", requires=("play_waveforms",))
        .computes(build_program)
        .state_each(
            _literal_table(
                [{"slot": 0}],
                slot=authoring.ScalarType(authoring.IntType()),
            ),
            resource_port="source",
            capability="play_waveforms",
            field="program",
            value=build_program.output,
        )
        .build()
    )
    parent = (
        authoring.module_body(id="test.collection_state.compute_payload_parent")
        .use(child.instantiate("payload-child"))
        .build()
    )
    template = template_fixture(
        parent,
        id="test.collection_state.compute_payload",
        kind="collection_state",
    )

    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )

    state = core_state(resolved.experiment)[0]
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
        authoring.module_body(id="test.collection_state.relation_child")
        .inputs(rows)
        .resource("source", requires=("set_offset",))
        .state_each(
            rows,
            resource_port="source",
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
        authoring.module_body(id="test.collection_state.relation_parent")
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
    template = template_fixture(
        parent,
        id="test.collection_state.relation",
        kind="collection_state",
        scans=(
            axis(
                authoring.coordinate(
                    "bias",
                    authoring.ScalarType(authoring.FloatType()),
                ),
                (0.25, 0.5),
            ),
        ),
    )

    resolved = resolve_experiment(
        template.bind(),
        config_profile=load_config(),
    )

    assert _state_values(resolved) == [
        (0, "relation-child/source", 1.25),
        (1, "relation-child/source", 1.5),
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
        authoring.module_body(id="test.collection_state.writer")
        .inputs(writer_rows)
        .resource("source", requires=("set_offset",))
        .state_each(
            writer_rows,
            resource_port="source",
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
        authoring.module_body(id="test.collection_state.middle")
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
        authoring.module_body(id="test.collection_state.outer")
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
    template = template_fixture(
        parent,
        id="test.collection_state.nested",
        kind="collection_state",
        scans=(
            axis(
                authoring.coordinate(
                    "point_bias",
                    authoring.ScalarType(authoring.FloatType()),
                ),
                (0.25, 0.5),
            ),
        ),
    )

    resolved = resolve_experiment(
        template.bind(
            state_rows=({"resource_id": "source-a", "base": 1.0},),
        ),
        config_profile=load_config(),
    )

    assert _state_values(resolved) == [
        (0, "middle/writer/source", 1.25),
        (1, "middle/writer/source", 1.5),
    ]


def test_state_each_rejects_unguarded_optional_column_access() -> None:
    rows_type = _state_rows_type()
    rows = authoring.input("rows", rows_type)
    module = (
        authoring.module_body(id="test.collection_state.optional_column")
        .inputs(rows)
        .resource("source", requires=("set_offset",))
        .state_each(
            rows,
            resource_port="source",
            capability="set_offset",
            field="offset",
            value=lambda row: row["adjusted"],
        )
        .build()
    )
    template = template_fixture(
        module,
        id="test.collection_state.optional_column",
        kind="collection_state",
    )

    with pytest.raises(CheckFailed) as caught:
        resolve_experiment(
            template.bind(
                rows=({"resource_id": "source-a", "base": 1.0},),
            ),
            config_profile=load_config(),
        )

    assert caught.value.problems[0].code == "relation_plan_optional_column_access"


def test_state_each_validates_resource_port_capability() -> None:
    module = (
        authoring.module_body(id="test.collection_state.capability")
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
    template = template_fixture(
        module,
        id="test.collection_state.capability",
        kind="collection_state",
    )

    with pytest.raises(CheckFailed) as error:
        resolve_experiment(
            template.bind(),
            config_profile=load_config(),
        )

    assert error.value.problems[0].code == ("module_resource_port_capability_missing")

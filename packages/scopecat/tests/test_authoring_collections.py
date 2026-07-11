from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

import scopecat.authoring as authoring
from scopecat._compiler.binding import bind_program
from scopecat._compiler.ids import NodeId
from scopecat._compiler.program import ComputeEdge, ValueInput
from scopecat._compute_result import ComputeResultRef
from scopecat._relations import (
    EvalContext,
    ParameterRelationData,
    literal_rows,
)
from scopecat._value_expressions import (
    ScalarValueExpr,
    SeriesValueExpr,
    TableValueExpr,
)
from scopecat.authoring._module_composition import assemble_module_internal
from scopecat.authoring._resolution import ResolvedExperiment, resolve_experiment
from scopecat.authoring._value_refs import internal_value_ref_from_expression
from scopecat.errors import ValidationFailed
from scopecat.models.entity import EntityRef
from tests.support.authoring import load_config
from tests.support.experiment_preview import preview_contract


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
    points = resolved.experiment.point_source.expr.evaluate(resolved.parameters)
    return [
        (record.point_index, record.resource, record.value)
        for point_index, point in enumerate(points)
        for record in resolved.experiment.state[0].evaluate(
            point_index=point_index,
            ctx=EvalContext(params=resolved.parameters, row=point),
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
    parent = (
        authoring.module("test.collections.parent")
        .inputs(gate_rows, offset_values)
        .use(
            child(
                gates=gate_rows,
                offsets=offset_values,
            )
        )
        .build()
    )
    template = (
        parent.template("test.collections", kind="collections")
        .experiment_id("collections")
        .record_product("signal")
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
        workspace=Path("/tmp/scopecat-test"),
        config_profile=config,
    )
    experiment = resolved.experiment

    node = experiment.compute_nodes[0]
    rows = node.inputs["rows"]
    assert isinstance(rows, ValueInput)
    assert rows.source_inputs == ("gate_rows",)
    assert isinstance(rows.value, TableValueExpr)
    assert rows.value.expr.evaluate() == [
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
    assert offset_values.source_inputs == ("offset_values",)
    assert isinstance(offset_values.value, SeriesValueExpr)
    assert offset_values.value.expr.evaluate(EvalContext()) == [0.25, 0.5]

    route_entities = experiment.route_intents[0].entity_exprs[0]
    assert isinstance(route_entities, SeriesValueExpr)
    assert route_entities.expr.evaluate(EvalContext()) == [EntityRef(id="q0")]

    axis = experiment.records[0].axes[0]
    assert axis.size == 1
    assert axis.metadata == {
        "entity_kind": "logical_device",
        "entities": [{"id": "q0", "kind": "logical_device", "metadata": {}}],
    }

    preview = preview_contract(
        experiment,
        resolved.parameters,
        config=config,
    )
    assert preview.routes[0].resolved[0].entity_ids == ("q0",)


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
        .use(child(rows=(), items=({"label": "first"},)))
        .build()
    )
    template = (
        parent.template("test.collection_literals", kind="collection_literals")
        .experiment_id("collection-literals")
        .build()
    )

    resolved = resolve_experiment(
        template.bind(),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )
    node = resolved.experiment.compute_nodes[0]

    rows = node.inputs["rows"]
    assert isinstance(rows, ValueInput)
    assert isinstance(rows.value, TableValueExpr)
    assert rows.value.expr.evaluate() == []

    items = node.inputs["items"]
    assert isinstance(items, ValueInput)
    assert isinstance(items.value, SeriesValueExpr)
    assert items.value.expr.evaluate(EvalContext()) == [{"label": "first"}]


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
        .use(leaf(value=value, items=items, rows=rows))
        .build()
    )
    outer = (
        authoring.module("test.same_name.outer")
        .inputs(value, items, rows)
        .use(middle(value=value, items=items, rows=rows))
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
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )
    node = resolved.experiment.compute_nodes[0]
    points = resolved.experiment.point_source.expr.evaluate(resolved.parameters)

    scalar = node.inputs["value"]
    assert isinstance(scalar, ValueInput)
    assert isinstance(scalar.value, ScalarValueExpr)
    assert scalar.value.expr.eval(EvalContext(row=points[1])) == 0.5
    series = node.inputs["items"]
    assert isinstance(series, ValueInput)
    assert isinstance(series.value, SeriesValueExpr)
    assert series.value.expr.evaluate(EvalContext()) == [1.0, 2.0]
    table = node.inputs["rows"]
    assert isinstance(table, ValueInput)
    assert isinstance(table.value, TableValueExpr)
    assert table.value.expr.evaluate() == [{"resource_id": "source-a", "base": 1.0}]


def test_template_accepts_unbound_input_port_from_nested_module() -> None:
    value = authoring.input(
        "value",
        authoring.ScalarType(authoring.FloatType()),
    )
    child = authoring.module("test.nested_port.child").inputs(value).build()
    root = authoring.module("test.nested_port.root").use(child).build()
    template = root.template("test.nested_port", kind="nested_port").build()

    resolve_experiment(
        template.bind(value=1),
        workspace=Path("/tmp/scopecat-test"),
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
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )
    plan = bind_program(resolved.experiment, resolved.environment)
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

    assert error.value.path == "scan.values[0]"
    assert error.value.reason == "value must be at least 1"


def test_module_invocation_rejects_collection_shape_mismatch() -> None:
    rows = authoring.input("rows", _gate_table_type())
    child = authoring.module("test.collection_shape.child").inputs(rows).build()
    items = authoring.input(
        "items",
        authoring.SeriesType(_entity_scalar()),
    )
    parent = (
        authoring.module("test.collection_shape.parent")
        .inputs(items)
        .use(child(rows=items))
        .build()
    )

    with pytest.raises(
        authoring.ValueValidationError,
        match=r"expected Table\{.*\}, got Series\[Scalar\[Entity\]\]",
    ):
        assemble_module_internal(parent, items=("q0",))


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
    parent = (
        authoring.module("test.collection_atom.parent")
        .inputs(numbers)
        .use(child(entities=numbers))
        .build()
    )

    with pytest.raises(
        authoring.ValueValidationError,
        match=r"expected Series\[Scalar\[Entity\]\], got Series\[Scalar\[Float\]\]",
    ):
        assemble_module_internal(parent, numbers=(1.0,))


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
    quantity_parent = (
        authoring.module("test.quantity_type.parent")
        .inputs(duration)
        .use(quantity_child(frequency=duration))
        .build()
    )

    with pytest.raises(authoring.ValueValidationError, match=r"Quantity\[GHz\]"):
        assemble_module_internal(quantity_parent, duration=1.0)

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
    table_parent = (
        authoring.module("test.table_type.parent")
        .inputs(rows)
        .use(table_child(gates=rows))
        .build()
    )

    with pytest.raises(
        authoring.ValueValidationError,
        match=r"control: Scalar\[Entity\]",
    ):
        assemble_module_internal(table_parent, rows=({"control": 0.0, "target": 1.0},))


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
        .use(child(program=middle_program))
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
        .use(middle(program=produce.output))
        .build()
    )

    assembly = assemble_module_internal(
        parent,
    )
    consumer = next(node for node in assembly.compute_nodes if node.id == "consume")
    assert dict(consumer.inputs)["program"] == produce.output
    resolved = resolve_experiment(
        parent.template("test.compute_edge", kind="compute_edge").build().bind(),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )
    linked_consumer = next(
        node
        for node in resolved.experiment.compute_nodes
        if node.id.local_id == "consume"
    )
    program_edge = linked_consumer.inputs["program"]
    assert isinstance(program_edge, ComputeEdge)
    assert program_edge.producer == NodeId(local_id="produce")

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
    incompatible_parent = (
        authoring.module("test.compute_edge.incompatible_parent")
        .computes(incompatible_produce)
        .use(incompatible_child(program=incompatible_produce.output))
        .build()
    )

    with pytest.raises(authoring.ValueValidationError, match=r"Payload\[waveform\]"):
        assemble_module_internal(
            incompatible_parent,
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
        .use(child(values=produce.output))
        .build()
    )

    resolved = resolve_experiment(
        parent.template("test.compute_series", kind="compute_series").build().bind(),
        workspace=Path("/tmp/scopecat-test"),
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
    assert produce.output_type == float_series
    values_edge = consume.inputs["values"]
    assert isinstance(values_edge, ComputeEdge)
    assert values_edge.producer == NodeId(local_id="produce-series")


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

    with pytest.raises(ValidationFailed) as error:
        resolve_experiment(
            required.bind(label=None),
            workspace=Path("/tmp/scopecat-test"),
            config_profile=load_config(),
        )
    assert error.value.diagnostics[0].code == "module_input_type_mismatch"
    assert "value must not be null" in error.value.diagnostics[0].message

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
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )

    value_input = resolved.experiment.compute_nodes[0].inputs["label"]
    assert isinstance(value_input, ValueInput)
    value = value_input.value
    assert isinstance(value, ScalarValueExpr)
    assert value.expr.value is None


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
            field="set_offset.offset",
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
            child(
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
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )
    assert _state_values(resolved) == [
        (0, "source-a", 1.25),
        (0, "source-b", 2.25),
        (1, "source-a", 1.5),
        (1, "source-b", 2.5),
    ]


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
            field="set_frequency.frequency",
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
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )

    state = resolved.experiment.state[0]
    assert state.state is not None
    route_entities = state.state[0].route_entities
    assert isinstance(route_entities[0], ScalarValueExpr)
    assert isinstance(route_entities[1], SeriesValueExpr)

    records = state.evaluate(
        point_index=0,
        ctx=EvalContext(params=ParameterRelationData(), row={}),
    )
    assert records[0].route_entities == [EntityRef(id="q0")]


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
            field="play_waveforms.program",
            value=build_program.output,
        )
        .build()
    )
    parent = (
        authoring.module("test.collection_state.compute_payload_parent")
        .use(child(resource_id="source-a"))
        .build()
    )
    template = parent.template(
        "test.collection_state.compute_payload",
        kind="collection_state",
    ).build()

    resolved = resolve_experiment(
        template.bind(),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )

    state = resolved.experiment.state[0]
    assert state.state is not None
    assert state.state[0].value == ComputeResultRef(
        node_id=NodeId(
            scope=("test.collection_state.compute_payload_child[0]",),
            local_id="build-program",
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
            field="set_offset.offset",
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
            child(
                rows=_literal_table(
                    [{"resource_id": "source-a", "base": 1.0}],
                    resource_id=authoring.ScalarType(authoring.StringType()),
                    base=authoring.ScalarType(authoring.FloatType()),
                ).with_columns(lambda row: {"adjusted": row["base"] + bias})
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
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )

    assert _state_values(resolved) == [
        (0, "source-a", 1.25),
        (1, "source-a", 1.5),
    ]


def test_state_each_preserves_outer_scope_across_two_module_boundaries() -> None:
    state_rows = _state_rows_type()
    writer_rows = authoring.input("rows", state_rows)
    writer = (
        authoring.module("test.collection_state.writer")
        .inputs(writer_rows)
        .state_each(
            writer_rows,
            resource=lambda row: row["resource_id"],
            field="set_offset.offset",
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
            writer(
                rows=middle_rows.with_columns(
                    lambda row: {"adjusted": row["base"] + middle_bias}
                )
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
            middle(
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
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )

    assert _state_values(resolved) == [
        (0, "source-a", 1.25),
        (1, "source-a", 1.5),
    ]


def test_state_each_treats_resource_string_as_a_fixed_resource_id() -> None:
    module = (
        authoring.module("test.collection_state.fixed_resource")
        .state_each(
            _literal_table(
                [{"value": 1.0}],
                value=authoring.ScalarType(authoring.FloatType()),
            ),
            resource="fixed-source",
            field="set_offset.offset",
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
        workspace=Path("/tmp/scopecat-test"),
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
            field="set_power.value",
            value=lambda row: row["value"],
        )
        .build()
    )
    template = module.template(
        "test.collection_state.capability",
        kind="collection_state",
    ).build()

    with pytest.raises(ValidationFailed) as error:
        resolve_experiment(
            template.bind(),
            workspace=Path("/tmp/scopecat-test"),
            config_profile=load_config(),
        )

    assert error.value.diagnostics[0].code == (
        "module_resource_port_capability_missing"
    )

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

import scopecat.authoring as authoring
from scopecat.errors import ValidationFailed
from scopecat.experiments import (
    ExperimentSpec,
    ScalarValueExpr,
    SeriesValueExpr,
    TableValueExpr,
)
from scopecat.models.entity import EntityRef
from scopecat.relations import EvalContext, ParameterRelationData, col, literal_rows
from tests.support.authoring import load_config
from tests.support.experiment_preview import preview_contract


def _echo_inputs(**inputs: object) -> dict[str, object]:
    return inputs


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
        )
    )


def _state_values(
    resolved: authoring.ResolvedExperiment,
) -> list[tuple[int, str, object]]:
    points = resolved.experiment.points.evaluate(resolved.parameter_view)
    params = ParameterRelationData.from_parameter_view(resolved.parameter_view)
    return [
        (record.point_index, record.resource, record.value)
        for point_index, point in enumerate(points)
        for record in resolved.experiment.state[0].evaluate(
            point_index=point_index,
            ctx=EvalContext(params=params, row=point),
        )
    ]


def test_collections_cross_module_route_axis_and_compute_with_provenance() -> None:
    gate_table = _gate_table_type()
    offsets = authoring.SeriesType(authoring.ScalarType(authoring.FloatType()))
    gates = authoring.input_table("gates")
    gate_entities = gates.entities("control", "target")
    child = (
        authoring.module("test.collections.child")
        .input("gates", value_type=gate_table)
        .input("offsets", value_type=offsets)
        .resource(
            "source",
            requires=authoring.requires(
                "set_frequency",
                for_entities=(gate_entities,),
            ),
        )
        .compute(
            "prepare",
            fn=_echo_inputs,
            inputs={
                "rows": gates,
                "offsets": authoring.input_series("offsets"),
            },
        )
        .product(
            "signal",
            resource="source",
            axes=(authoring.entity_axis("qubit", gate_entities),),
        )
        .build()
    )
    parent = (
        authoring.module("test.collections.parent")
        .input("gate_rows", value_type=gate_table)
        .input("offset_values", value_type=offsets)
        .use(
            child(
                gates=authoring.input_table("gate_rows"),
                offsets=authoring.input_series("offset_values"),
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
    resolved = authoring.resolve_experiment(
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
    experiment = ExperimentSpec.model_validate_json(
        resolved.experiment.model_dump_json()
    )

    node = experiment.compute_nodes[0]
    rows = node.inputs["rows"]
    assert rows.source_inputs == ["gate_rows"]
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
    assert offset_values.source_inputs == ["offset_values"]
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
        resolved.parameter_view,
        config=config,
    )
    assert preview.routes[0].resolved[0].entity_ids == ("q0",)


def test_resource_entity_series_rejects_non_entity_members_during_authoring() -> None:
    module = (
        authoring.module("test.invalid_resource_entities")
        .input(
            "items",
            value_type=authoring.SeriesType(
                authoring.ScalarType(authoring.FloatType())
            ),
        )
        .resource(
            "source",
            requires=authoring.requires("set_frequency", for_entities=("items",)),
        )
        .build()
    )
    template = module.template(
        "test.invalid_resource_entities",
        kind="invalid_resource_entities",
    ).build()

    with pytest.raises(ValidationFailed) as error:
        authoring.resolve_experiment(
            template.bind(items=(1.0,)),
            workspace=Path("/tmp/scopecat-test"),
            config_profile=load_config(),
        )

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "module_resource_entity_input_invalid"
    assert diagnostic.path == "inputs.items"

    table_source = cast("Any", authoring.input_table("items"))
    table_module = (
        authoring.module("test.invalid_resource_entity_table")
        .resource(
            "source",
            requires=authoring.requires(
                "set_frequency",
                for_entities=(table_source,),
            ),
        )
        .build()
    )
    table_template = table_module.template(
        "test.invalid_resource_entity_table",
        kind="invalid_resource_entities",
    ).build()

    with pytest.raises(ValidationFailed) as error:
        authoring.resolve_experiment(
            table_template.bind(),
            workspace=Path("/tmp/scopecat-test"),
            config_profile=load_config(),
        )
    assert error.value.diagnostics[0].code == "module_resource_entity_input_invalid"


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
    child = (
        authoring.module("test.collection_literals.child")
        .input("rows", value_type=_gate_table_type())
        .input("items", value_type=records)
        .compute(
            "inspect",
            fn=_echo_inputs,
            inputs={
                "rows": authoring.input_table("rows"),
                "items": authoring.input_series("items"),
            },
        )
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

    resolved = authoring.resolve_experiment(
        template.bind(),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )
    node = resolved.experiment.compute_nodes[0]

    rows = node.inputs["rows"]
    assert isinstance(rows.value, TableValueExpr)
    assert rows.value.expr.evaluate() == []

    items = node.inputs["items"]
    assert isinstance(items.value, SeriesValueExpr)
    assert items.value.expr.evaluate(EvalContext()) == [{"label": "first"}]


def test_same_name_inputs_pass_through_multiple_module_boundaries() -> None:
    scalar_type = authoring.ScalarType(authoring.FloatType())
    series_type = authoring.SeriesType(scalar_type)
    table_type = _state_rows_type()
    leaf = (
        authoring.module("test.same_name.leaf")
        .input("value", value_type=scalar_type)
        .input("items", value_type=series_type)
        .input("rows", value_type=table_type)
        .compute(
            "inspect",
            fn=_echo_inputs,
            inputs={
                "value": authoring.input_ref("value"),
                "items": authoring.input_series("items"),
                "rows": authoring.input_table("rows"),
            },
        )
        .build()
    )
    middle = (
        authoring.module("test.same_name.middle")
        .input("value", value_type=scalar_type)
        .input("items", value_type=series_type)
        .input("rows", value_type=table_type)
        .use(
            leaf(
                value=authoring.input_ref("value"),
                items=authoring.input_series("items"),
                rows=authoring.input_table("rows"),
            )
        )
        .build()
    )
    outer = (
        authoring.module("test.same_name.outer")
        .input("value", value_type=scalar_type)
        .input("items", value_type=series_type)
        .input("rows", value_type=table_type)
        .use(
            middle(
                value=authoring.input_ref("value"),
                items=authoring.input_series("items"),
                rows=authoring.input_table("rows"),
            )
        )
        .build()
    )
    template = (
        outer.template("test.same_name", kind="same_name")
        .scan("value", (0.25, 0.5))
        .build()
    )

    resolved = authoring.resolve_experiment(
        template.bind(
            items=(1.0, 2.0),
            rows=({"resource_id": "source-a", "base": 1.0},),
        ),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )
    node = resolved.experiment.compute_nodes[0]
    points = resolved.experiment.points.evaluate(resolved.parameter_view)

    scalar = node.inputs["value"]
    assert isinstance(scalar.value, ScalarValueExpr)
    assert scalar.value.expr.eval(EvalContext(row=points[1])) == 0.5
    series = node.inputs["items"]
    assert isinstance(series.value, SeriesValueExpr)
    assert series.value.expr.evaluate(EvalContext()) == [1.0, 2.0]
    table = node.inputs["rows"]
    assert isinstance(table.value, TableValueExpr)
    assert table.value.expr.evaluate() == [{"resource_id": "source-a", "base": 1.0}]


def test_template_accepts_unbound_input_port_from_nested_module() -> None:
    child = (
        authoring.module("test.nested_port.child")
        .input(
            "value",
            value_type=authoring.ScalarType(authoring.FloatType()),
        )
        .build()
    )
    root = authoring.module("test.nested_port.root").use(child).build()
    template = root.template("test.nested_port", kind="nested_port").build()

    authoring.resolve_experiment(
        template.bind(value=1),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )


def test_scan_points_are_coerced_by_same_named_scalar_input_type() -> None:
    module = (
        authoring.module("test.scan_coercion")
        .input(
            "value",
            value_type=authoring.ScalarType(authoring.FloatType()),
        )
        .build()
    )
    template = (
        module.template("test.scan_coercion", kind="scan_coercion")
        .scan("value", (1,))
        .build()
    )

    resolved = authoring.resolve_experiment(
        template.bind(),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )
    value = resolved.experiment.points.evaluate(resolved.parameter_view)[0]["value"]

    assert value == 1.0
    assert isinstance(value, float)


def test_scan_points_reject_same_named_scalar_input_constraint_violation() -> None:
    module = (
        authoring.module("test.scan_constraint")
        .input(
            "count",
            value_type=authoring.ScalarType(authoring.IntType(minimum=1)),
        )
        .build()
    )
    template = (
        module.template("test.scan_constraint", kind="scan_constraint")
        .scan("count", (0,))
        .build()
    )

    with pytest.raises(ValidationFailed) as error:
        authoring.resolve_experiment(
            template.bind(),
            workspace=Path("/tmp/scopecat-test"),
            config_profile=load_config(),
        )

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "module_point_value_type_mismatch"
    assert diagnostic.path == "points.0.count"
    assert "value must be at least 1" in diagnostic.message


def test_module_invocation_rejects_collection_shape_mismatch() -> None:
    child = (
        authoring.module("test.collection_shape.child")
        .input("rows", value_type=_gate_table_type())
        .build()
    )
    parent = (
        authoring.module("test.collection_shape.parent")
        .input(
            "items",
            value_type=authoring.SeriesType(_entity_scalar()),
        )
        .use(child(rows=authoring.input_series("items")))
        .build()
    )

    with pytest.raises(
        authoring.ValueValidationError,
        match="expected table-shaped expression, got series-shaped expression",
    ):
        parent.assemble(items=("q0",))


def test_explicit_null_is_validated_as_a_value_not_treated_as_unbound() -> None:
    required = (
        authoring.module("test.null.required")
        .input(
            "label",
            value_type=authoring.ScalarType(authoring.StringType()),
        )
        .build()
        .template("test.null.required", kind="null")
        .build()
    )

    with pytest.raises(ValidationFailed) as error:
        authoring.resolve_experiment(
            required.bind(label=None),
            workspace=Path("/tmp/scopecat-test"),
            config_profile=load_config(),
        )
    assert error.value.diagnostics[0].code == "module_input_type_mismatch"
    assert "value must not be null" in error.value.diagnostics[0].message

    nullable = (
        authoring.module("test.null.nullable")
        .input(
            "label",
            value_type=authoring.ScalarType(
                authoring.StringType(),
                nullable=True,
            ),
        )
        .compute(
            "inspect",
            fn=_echo_inputs,
            inputs={"label": authoring.input_ref("label")},
        )
        .build()
        .template("test.null.nullable", kind="null")
        .build()
    )
    resolved = authoring.resolve_experiment(
        nullable.bind(label=None),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )

    value = resolved.experiment.compute_nodes[0].inputs["label"].value
    assert isinstance(value, ScalarValueExpr)
    assert value.expr.value is None


def test_table_input_drives_child_state_with_outer_scanned_input() -> None:
    state_rows = _state_rows_type()
    child = (
        authoring.module("test.collection_state.child")
        .input("rows", value_type=state_rows)
        .input(
            "bias",
            value_type=authoring.ScalarType(authoring.FloatType()),
        )
        .state_each(
            authoring.input_table("rows"),
            resource=col("resource_id"),
            field="set_offset.offset",
            value=col("base") + authoring.input_ref("bias"),
        )
        .build()
    )
    parent = (
        authoring.module("test.collection_state.parent")
        .input("state_rows", value_type=state_rows)
        .input(
            "point_bias",
            value_type=authoring.ScalarType(authoring.FloatType()),
        )
        .use(
            child(
                rows=authoring.input_table("state_rows"),
                bias=authoring.input_ref("point_bias"),
            )
        )
        .build()
    )
    template = (
        parent.template("test.collection_state", kind="collection_state")
        .experiment_id("collection-state")
        .scan("point_bias", (0.25, 0.5))
        .build()
    )

    resolved = authoring.resolve_experiment(
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
    module = (
        authoring.module("test.collection_state.routes")
        .input("qubits", value_type=entity_series)
        .state_each(
            literal_rows([{"resource_id": "source-0"}]),
            resource=col("resource_id"),
            field="set_frequency.frequency",
            value=1.0,
            route_entities=(EntityRef(id="q0"), authoring.input_series("qubits")),
        )
        .build()
    )
    template = module.template(
        "test.collection_state.routes",
        kind="collection_state",
    ).build()
    resolved = authoring.resolve_experiment(
        template.bind(qubits=("q0",)),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )

    restored = ExperimentSpec.model_validate_json(resolved.experiment.model_dump_json())
    state = restored.state[0]
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
    child = (
        authoring.module("test.collection_state.compute_payload_child")
        .input(
            "resource_id",
            value_type=authoring.ScalarType(authoring.StringType()),
        )
        .compute(
            "build-program",
            fn=_echo_inputs,
            output_type=authoring.ScalarType(authoring.PayloadType("pulse_program")),
        )
        .state_each(
            literal_rows([{"slot": 0}]),
            resource=authoring.input_ref("resource_id"),
            field="play_waveforms.program",
            value=authoring.compute_result("build-program"),
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

    resolved = authoring.resolve_experiment(
        template.bind(),
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )

    state = resolved.experiment.state[0]
    assert state.state is not None
    assert state.state[0].value == authoring.ComputeResultRef(node_id="build-program")


def test_state_each_resolves_inputs_nested_inside_a_relation() -> None:
    state_rows = _state_rows_type()
    child = (
        authoring.module("test.collection_state.relation_child")
        .input("rows", value_type=state_rows)
        .state_each(
            authoring.input_table("rows"),
            resource=col("resource_id"),
            field="set_offset.offset",
            value=col("adjusted"),
        )
        .build()
    )
    parent = (
        authoring.module("test.collection_state.relation_parent")
        .input(
            "bias",
            value_type=authoring.ScalarType(authoring.FloatType()),
        )
        .use(
            child(
                rows=literal_rows(
                    [{"resource_id": "source-a", "base": 1.0}]
                ).with_columns(adjusted=col("base") + authoring.input_ref("bias"))
            )
        )
        .build()
    )
    template = (
        parent.template("test.collection_state.relation", kind="collection_state")
        .scan("bias", (0.25, 0.5))
        .build()
    )

    resolved = authoring.resolve_experiment(
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
    writer = (
        authoring.module("test.collection_state.writer")
        .input("rows", value_type=state_rows)
        .state_each(
            authoring.input_table("rows"),
            resource=col("resource_id"),
            field="set_offset.offset",
            value=col("adjusted"),
        )
        .build()
    )
    middle = (
        authoring.module("test.collection_state.middle")
        .input("rows", value_type=state_rows)
        .input(
            "bias",
            value_type=authoring.ScalarType(authoring.FloatType()),
        )
        .use(
            writer(
                rows=authoring.input_table("rows").with_columns(
                    adjusted=col("base") + authoring.input_ref("bias")
                )
            )
        )
        .build()
    )
    parent = (
        authoring.module("test.collection_state.outer")
        .input("state_rows", value_type=state_rows)
        .input(
            "point_bias",
            value_type=authoring.ScalarType(authoring.FloatType()),
        )
        .use(
            middle(
                rows=authoring.input_table("state_rows"),
                bias=col("point_bias"),
            )
        )
        .build()
    )
    template = (
        parent.template("test.collection_state.nested", kind="collection_state")
        .scan("point_bias", (0.25, 0.5))
        .build()
    )

    resolved = authoring.resolve_experiment(
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
            literal_rows([{"value": 1.0}]),
            resource="fixed-source",
            field="set_offset.offset",
            value=col("value"),
        )
        .build()
    )
    template = module.template(
        "test.collection_state.fixed_resource",
        kind="collection_state",
    ).build()

    resolved = authoring.resolve_experiment(
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
            literal_rows([{"value": 1.0}]),
            resource_port="source",
            field="set_power.value",
            value=col("value"),
        )
        .build()
    )
    template = module.template(
        "test.collection_state.capability",
        kind="collection_state",
    ).build()

    with pytest.raises(ValidationFailed) as error:
        authoring.resolve_experiment(
            template.bind(),
            workspace=Path("/tmp/scopecat-test"),
            config_profile=load_config(),
        )

    assert error.value.diagnostics[0].code == (
        "module_resource_port_capability_missing"
    )

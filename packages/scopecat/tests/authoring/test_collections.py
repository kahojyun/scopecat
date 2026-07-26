from __future__ import annotations

from typing import Any, cast

import pytest

import scopecat.authoring as authoring
from scopecat.authoring.scans import axis
from scopecat.authoring.templates import ExperimentInvocation
from scopecat.compiler.frontend.assembly_linking import bind_verified_assembly
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
    SeriesValueExpr,
    TableValueExpr,
)
from scopecat.compiler.typed.point_domain import materialize_point_domain
from scopecat.compiler.typed.program import (
    ComputeEdge,
    CoreProgram,
    ValueInput,
)
from scopecat.config.environment import build_config_environment
from scopecat.execution.local.program import CollectOperation
from scopecat.graph.relations.model import LiteralScalarExpr
from scopecat.graph.values import (
    OperationId,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.symbols import SymbolId
from scopecat.records.config import ConfigProfileSnapshot
from tests.testkit.authoring import link_invocation, load_config, template_fixture
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


def _bind_program(
    invocation: ExperimentInvocation,
    config: ConfigProfileSnapshot,
) -> CoreProgram:
    environment = build_config_environment(config)
    compiled = compile_invocation(invocation)
    return bind_verified_assembly(compiled.assembly, environment)


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


def test_collections_cross_module_resource_entity_axis_with_provenance() -> None:
    gate_table = _gate_table_type()
    offsets_type = authoring.SeriesType(authoring.ScalarType(authoring.FloatType()))
    entities_type = authoring.SeriesType(_entity_scalar())
    gates = authoring.input("gates", gate_table)
    offsets = authoring.input("offsets", offsets_type)
    gate_entities = authoring.input("entities", entities_type)
    prepare = authoring.compute(
        "prepare",
        fn=_echo_rows_offsets,
        inputs={"rows": gates, "offsets": offsets},
        output_type=authoring.ScalarType(authoring.PayloadType("prepared")),
    )
    child = (
        authoring.module_body(id="test.collections.child")
        .inputs(gates, offsets, gate_entities)
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
    entity_values = authoring.input("entity_values", entities_type)
    child_instance = child.instantiate(
        "collections-child",
        gates=gate_rows,
        offsets=offset_values,
        entities=entity_values,
    )
    parent = (
        authoring.module_body(id="test.collections.parent")
        .inputs(gate_rows, offset_values, entity_values)
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
    resolved = link_invocation(
        template.bind(
            gate_rows=(
                {"control": "q0", "target": "q0"},
                {"control": "q0", "target": "q0"},
            ),
            offset_values=(0.25, 0.5),
            entity_values=("q0",),
        ),
        config_profile=config,
    )
    experiment = _bind_program(
        template.bind(
            gate_rows=(
                {"control": "q0", "target": "q0"},
                {"control": "q0", "target": "q0"},
            ),
            offset_values=(0.25, 0.5),
            entity_values=("q0",),
        ),
        config,
    )

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
    ) == [EntityRef(id="q0", kind="logical_device")]

    axis = experiment.product_defs[0].axes[0]
    assert axis.size == 1
    assert axis.metadata == {
        "entity_kind": "logical_device",
        "entities": ({"id": "q0", "kind": "logical_device", "metadata": {}},),
    }

    preview = materialized_effects_contract(
        experiment,
        resolved.environment.parameters,
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

    program = _bind_program(
        template.bind(),
        load_config(),
    )
    node = program.compute_nodes[0]

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

    resolved = link_invocation(
        template.bind(
            items=(1.0, 2.0),
            rows=({"resource_id": "source-a", "base": 1.0},),
        ),
        config_profile=load_config(),
    )
    program = _bind_program(
        template.bind(
            items=(1.0, 2.0),
            rows=({"resource_id": "source-a", "base": 1.0},),
        ),
        load_config(),
    )
    node = program.compute_nodes[0]
    verified_program = resolved.verified_program
    points = [
        point.row
        for point in materialize_point_domain(
            verified_program.point_domain,
            resolved.environment.parameters,
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

    link_invocation(
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

    resolved = link_invocation(
        template.bind(),
        config_profile=load_config(),
    )
    plan = materialize_local_execution(resolved)
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

    program = _bind_program(
        template_fixture(
            parent,
            id="test.compute_series",
            kind="compute_series",
        ).bind(),
        load_config(),
    )
    produce = next(
        node for node in program.compute_nodes if node.id.local_id == "produce-series"
    )
    consume = next(
        node for node in program.compute_nodes if node.id.local_id == "consume-series"
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
        link_invocation(
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
    program = _bind_program(
        nullable.bind(label=None),
        load_config(),
    )

    value_input = program.compute_nodes[0].inputs["label"]
    assert isinstance(value_input, ValueInput)
    value = value_input.value
    assert isinstance(value, ScalarValueExpr)
    assert isinstance(value.plan.root, LiteralScalarExpr)
    assert value.plan.root.value is None

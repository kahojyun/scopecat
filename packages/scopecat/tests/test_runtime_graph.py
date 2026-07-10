import pytest
from pydantic import TypeAdapter, ValidationError

from scopecat._planning.compute_dependencies import (
    summarize_compute_node_dependencies,
)
from scopecat._planning.planner import PlannerPoint, build_planner_snapshot
from scopecat._runtime.graph import build_runtime_graph
from scopecat._runtime.lowering import (
    compile_desired_state_points,
    evaluate_compute_nodes_for_point,
)
from scopecat.experiments import (
    ComputeNodeContext,
    ComputeNodeInput,
    ComputeNodeOutputType,
    ComputeNodeSpec,
    ExperimentSpec,
    PointRouteBinding,
    ScalarValueExpr,
    StateRecord,
    StateSpec,
    as_value_expr,
    compute_result,
    experiment,
    observable,
    set_state,
)
from scopecat.models.config import RoutingChannelBinding
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity
from scopecat.models.state import PayloadRef
from scopecat.models.value import ComputeResultRef, PayloadValue
from scopecat.relations import (
    EvalContext,
    ParameterRelationData,
    ScalarExpr,
    col,
    grid,
    input_series,
    input_table,
    lit,
    param,
    table,
    values,
)
from scopecat.value_types import Float, Payload, Scalar
from tests.support.parameter_fixtures import (
    parameter_view as _parameter_view,
)


def test_runtime_graph_compiles_product_bindings() -> None:
    spec = experiment(
        id="product-binding",
        kind="diagnostic",
        points=grid(index=[0]),
        records=[
            observable("signal", unit="ratio", resource="source-0"),
            observable(
                "raw_i",
                unit="ratio",
                resource="readout-stack",
                product_key="i",
            ),
        ],
    )

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameter_view()))

    assert "schema_version" not in graph.__dict__
    assert "plan_hash" not in graph.__dict__
    assert [point.point_index for point in graph.points] == [0]
    assert graph.points[0].coordinates == {"index": 0}
    assert [
        instruction.model_dump(mode="json") for instruction in graph.points[0].collect
    ] == [
        {
            "point_index": 0,
            "instrument_id": "source-0",
            "products": [
                {
                    "record_id": "signal",
                    "instrument_id": "source-0",
                    "product_key": "signal",
                    "kind": "observable",
                    "capability": None,
                    "unit": "ratio",
                    "dtype": "float64",
                    "axes": [],
                    "metadata": {},
                }
            ],
        },
        {
            "point_index": 0,
            "instrument_id": "readout-stack",
            "products": [
                {
                    "record_id": "raw_i",
                    "instrument_id": "readout-stack",
                    "product_key": "i",
                    "kind": "observable",
                    "capability": None,
                    "unit": "ratio",
                    "dtype": "float64",
                    "axes": [],
                    "metadata": {},
                }
            ],
        },
    ]
    assert [binding.model_dump(mode="json") for binding in graph.product_bindings] == [
        {
            "record_id": "signal",
            "instrument_id": "source-0",
            "product_key": "signal",
            "kind": "observable",
            "capability": None,
            "unit": "ratio",
            "dtype": "float64",
            "axes": [],
            "metadata": {},
        },
        {
            "record_id": "raw_i",
            "instrument_id": "readout-stack",
            "product_key": "i",
            "kind": "observable",
            "capability": None,
            "unit": "ratio",
            "dtype": "float64",
            "axes": [],
            "metadata": {},
        },
    ]


def test_state_route_entities_reject_table_shape_and_invalid_series_members() -> None:
    with pytest.raises(
        TypeError,
        match="state route entity source must be scalar or series-shaped",
    ):
        set_state(
            "drive-a",
            "pulse.frequency",
            5.0,
            route_entities=(input_table("entities"),),
        )

    valid_state = set_state("drive-a", "pulse.frequency", 5.0)
    with pytest.raises(ValidationError):
        StateSpec.model_validate(
            {
                **valid_state.model_dump(mode="python"),
                "route_entities": [
                    {
                        "shape": "table",
                        "expr": input_table("entities"),
                    }
                ],
            }
        )

    entity_kind_state = set_state(
        "drive-a",
        "pulse.frequency",
        5.0,
        route_entities=({"id": "q0", "kind": "input"},),
    )
    restored = StateSpec.model_validate_json(entity_kind_state.model_dump_json())
    assert restored.evaluate(point_index=0, ctx=EvalContext())[0].route_entities == [
        EntityRef(id="q0", kind="input")
    ]
    with pytest.raises(ValidationError):
        StateSpec.model_validate(
            {
                **valid_state.model_dump(mode="python"),
                "route_entities": [lit("q0").model_dump(mode="python")],
            }
        )

    state = set_state(
        "drive-a",
        "pulse.frequency",
        5.0,
        route_entities=(values([1]),),
    )
    with pytest.raises(TypeError, match="state route entity must resolve"):
        state.evaluate(point_index=0, ctx=EvalContext())

    empty_state = set_state(
        "drive-a",
        "pulse.frequency",
        5.0,
        route_entities=(values([]), "q0"),
    )
    with pytest.raises(ValueError, match="state route entity series must not be empty"):
        empty_state.evaluate(point_index=0, ctx=EvalContext())


def test_compute_result_state_refs_and_producer_output_types_round_trip() -> None:
    ref = compute_result("build-waveform")
    state = set_state("drive-a", "play_waveforms.program", ref)

    assert state.model_dump(mode="json")["value"] == {"node_id": "build-waveform"}

    restored_state = StateSpec.model_validate_json(state.model_dump_json())
    assert isinstance(restored_state.value, ComputeResultRef)
    assert restored_state.value == ref

    spec = experiment(
        id="compute-payload-round-trip",
        kind="diagnostic",
        points=grid(index=[0]),
        state=[state],
        records=[],
    ).model_copy(
        update={
            "compute_nodes": [
                ComputeNodeSpec(
                    id="build-waveform",
                    output_type=Scalar(Payload("pulse_program")),
                )
            ]
        }
    )
    assert spec.model_dump(mode="json")["compute_nodes"][0]["output_type"] == {
        "type": "payload",
        "schema_id": "pulse_program",
    }
    restored_spec = ExperimentSpec.model_validate_json(spec.model_dump_json())

    assert restored_spec.schema_version == "scopecat.experiment_spec.v7"
    assert restored_spec.state[0].value == ref
    assert restored_spec.compute_nodes[0].output_type == Scalar(
        Payload("pulse_program")
    )


def test_compute_node_output_type_json_schema_is_payload_only() -> None:
    output_schema = TypeAdapter(ComputeNodeOutputType).json_schema(mode="validation")

    assert output_schema == {
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "type": {"type": "string", "const": "payload"},
                    "schema_id": {"type": "string", "minLength": 1},
                    "nullable": {"type": "boolean", "const": False},
                },
                "required": ["type", "schema_id"],
            }
        ]
    }


@pytest.mark.parametrize(
    "output_type",
    [
        Scalar(Float()),
        Scalar(Payload("pulse_program"), nullable=True),
        Scalar(Payload("pulse_program", python_type=dict)),
        {"type": "payload", "schema_id": ""},
    ],
)
def test_compute_node_rejects_invalid_output_types(output_type: object) -> None:
    with pytest.raises(ValidationError):
        ComputeNodeSpec.model_validate(
            {"id": "build-waveform", "output_type": output_type}
        )


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"node_id": ""},
        {"node_id": "build-waveform", "schema_id": "pulse_program"},
        {"node_id": "build-waveform", "kind": "compute_result"},
    ],
)
def test_state_spec_rejects_invalid_compute_result_refs(
    value: dict[str, object],
) -> None:
    state = set_state(
        "drive-a",
        "play_waveforms.program",
        compute_result("build-waveform"),
    )
    wire = state.model_dump(mode="json")
    wire["value"] = value

    with pytest.raises(ValidationError):
        StateSpec.model_validate(wire)


def test_state_and_experiment_specs_reject_legacy_compute_result_markers() -> None:
    state = set_state(
        "drive-a",
        "play_waveforms.program",
        compute_result("build-waveform"),
    )
    legacy_value = ScalarExpr(
        kind="literal",
        value={
            "kind": "compute_result",
            "node_id": "build-waveform",
            "payload_kind": "pulse_program",
        },
    )
    legacy_state_wire = state.model_dump(mode="json")
    legacy_state_wire["value"] = legacy_value.model_dump(mode="json")

    with pytest.raises(ValidationError, match="ComputeResultRef"):
        StateSpec.model_validate(legacy_state_wire)

    spec = experiment(
        id="legacy-compute-result-marker",
        kind="diagnostic",
        points=grid(index=[0]),
        state=[state],
        records=[],
    )
    legacy_spec_wire = spec.model_dump(mode="json")
    legacy_spec_wire["state"] = [legacy_state_wire]
    assert legacy_spec_wire["schema_version"] == "scopecat.experiment_spec.v7"

    with pytest.raises(ValidationError, match="ComputeResultRef"):
        ExperimentSpec.model_validate(legacy_spec_wire)


def test_nested_compute_result_shaped_dicts_are_not_payload_references() -> None:
    spec = experiment(
        id="nested-compute-result-shaped-dict",
        kind="diagnostic",
        points=grid(index=[0]),
        state=[
            set_state(
                "drive-a",
                "play_waveforms.program",
                {
                    "wrapper": {
                        "kind": "compute_result",
                        "node_id": "build-waveform",
                        "payload_kind": "pulse_program",
                    }
                },
            )
        ],
        records=[],
    ).model_copy(update={"compute_nodes": [ComputeNodeSpec(id="build-waveform")]})

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameter_view()))

    assert graph.payloads == ()
    assert graph.points[0].compute_steps[0].payload is None
    assert [diagnostic["code"] for diagnostic in graph.diagnostics] == [
        "state_value_unsupported"
    ]


def test_runtime_graph_reports_unknown_compute_result_nodes() -> None:
    spec = experiment(
        id="unknown-compute-payload-node",
        kind="diagnostic",
        points=grid(index=[0]),
        state=[
            set_state(
                "drive-a",
                "play_waveforms.program",
                compute_result("missing-node"),
            )
        ],
        records=[],
    )

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameter_view()))

    assert "compute_payload_unknown_node" in {
        diagnostic["code"] for diagnostic in graph.diagnostics
    }


def test_runtime_graph_reports_compute_result_without_output_type() -> None:
    spec = experiment(
        id="missing-compute-output-type",
        kind="diagnostic",
        points=grid(index=[0]),
        state=[
            set_state(
                "drive-a",
                "play_waveforms.program",
                compute_result("build-waveform"),
            ),
        ],
        records=[],
    ).model_copy(update={"compute_nodes": [ComputeNodeSpec(id="build-waveform")]})

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameter_view()))

    assert "compute_payload_output_type_required" in {
        diagnostic["code"] for diagnostic in graph.diagnostics
    }


def test_runtime_graph_deduplicates_payload_for_shared_compute_result() -> None:
    spec = experiment(
        id="shared-compute-payload",
        kind="diagnostic",
        points=grid(index=[0]),
        state=[
            set_state(
                "drive-a",
                "play_waveforms.program",
                compute_result("build-waveform"),
            ),
            set_state(
                "drive-a",
                "play_waveforms.preview",
                compute_result("build-waveform"),
            ),
        ],
        records=[],
    ).model_copy(
        update={
            "compute_nodes": [
                ComputeNodeSpec(
                    id="build-waveform",
                    output_type=Scalar(Payload("waveform_bundle")),
                )
            ]
        }
    )

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameter_view()))

    assert graph.diagnostics == ()
    assert [payload.id for payload in graph.payloads] == [
        "build-waveform.payload.point-0"
    ]
    assert len(graph.points[0].desired_state[0].fields) == 2


def test_typed_compute_output_is_only_materialized_when_state_references_it() -> None:
    spec = experiment(
        id="unreferenced-compute-payload",
        kind="diagnostic",
        points=grid(index=[0]),
        records=[],
    ).model_copy(
        update={
            "compute_nodes": [
                ComputeNodeSpec(
                    id="build-waveform",
                    output_type=Scalar(Payload("waveform_bundle")),
                )
            ]
        }
    )

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameter_view()))

    assert graph.diagnostics == ()
    assert graph.payloads == ()
    assert graph.points[0].compute_steps[0].payload is None


def test_state_route_channel_bindings_preserve_order_and_report_unbound_ids() -> None:
    record = StateRecord(
        point_index=0,
        resource="drive",
        field="pulse.frequency",
        value=5.0,
        route_entities=["q1", "q0"],
    )
    route_bindings = {
        0: [
            PointRouteBinding(
                port_id="drive",
                resource_id="drive-stack",
                capabilities=["pulse"],
                channel_bindings=[
                    RoutingChannelBinding(entity_id="q0", channel_id="channel-0"),
                    RoutingChannelBinding(entity_id="q1", channel_id="channel-1"),
                ],
            )
        ]
    }

    desired, diagnostics = compile_desired_state_points(
        [record],
        command_payload_ids=set(),
        unavailable_compute_payload_node_ids=frozenset(),
        route_bindings=route_bindings,
    )

    assert diagnostics == []
    assert [
        binding.entity_id for binding in desired[0][0].fields[0].channel_bindings
    ] == ["q1", "q0"]

    unbound_desired, diagnostics = compile_desired_state_points(
        [record.model_copy(update={"route_entities": ["q2"]})],
        command_payload_ids=set(),
        unavailable_compute_payload_node_ids=frozenset(),
        route_bindings=route_bindings,
    )
    assert {diagnostic["code"] for diagnostic in diagnostics} == {
        "state_route_entity_unbound"
    }
    assert unbound_desired == {}


def test_desired_state_reports_missing_compute_payload_materialization() -> None:
    desired, diagnostics = compile_desired_state_points(
        [
            StateRecord(
                point_index=0,
                resource="drive-a",
                field="play_waveforms.program",
                value=compute_result("build-waveform"),
            )
        ],
        command_payload_ids=set(),
        unavailable_compute_payload_node_ids=frozenset(),
        route_bindings={},
    )

    assert desired == {}
    assert [diagnostic["code"] for diagnostic in diagnostics] == [
        "compute_payload_not_materialized"
    ]


@pytest.mark.parametrize(
    "value",
    [
        True,
        float("nan"),
        float("inf"),
        10**1000,
        Quantity(value=float("nan"), unit="GHz"),
    ],
)
def test_desired_state_rejects_values_that_are_not_finite_numbers(
    value: bool | float | Quantity,
) -> None:
    desired, diagnostics = compile_desired_state_points(
        [
            StateRecord(
                point_index=0,
                resource="drive-a",
                field="pulse.gain",
                value=value,
            )
        ],
        command_payload_ids=set(),
        unavailable_compute_payload_node_ids=frozenset(),
        route_bindings={},
    )

    assert desired == {}
    assert [diagnostic["code"] for diagnostic in diagnostics] == [
        "state_value_unsupported"
    ]


def test_runtime_graph_is_transient_execution_surface() -> None:
    spec = experiment(
        id="runtime-graph-plan",
        kind="measurement",
        points=grid(index=[0]),
        records=[observable("signal", unit="ratio", resource="source-0")],
    )
    plan = build_planner_snapshot(spec, _parameter_view())

    graph = build_runtime_graph(plan)

    assert graph.experiment_id == spec.id
    assert graph.point_count == 1
    assert graph.expected_measurement_indices == {0}
    assert [point.point_index for point in graph.points] == [0]
    assert [binding.record_id for binding in graph.product_bindings] == ["signal"]
    assert "schema_version" not in graph.__dict__
    assert "content_hash" not in graph.__dict__


def test_runtime_graph_evaluates_generated_payload_nodes() -> None:
    def build_program(ctx: ComputeNodeContext) -> dict[str, object]:
        length = ctx.inputs["length"]
        assert length == Quantity(value=20.0, unit="ns")
        return {"length": length, "point_index": ctx.point_index}

    def render_waveforms(ctx: ComputeNodeContext) -> dict[str, object]:
        program = ctx.inputs["program"]
        assert isinstance(program, dict)
        return {"source_program": program["point_index"], "samples": [0.0, 0.5, 0.0]}

    spec = experiment(
        id="generated-waveform-plan",
        kind="diagnostic",
        points=grid(length=[Quantity(value=20.0, unit="ns")]),
        state=[
            set_state(
                "drive-a",
                "play_waveforms.program",
                compute_result("render-waveforms"),
            )
        ],
        records=[],
    ).model_copy(
        update={
            "compute_nodes": [
                ComputeNodeSpec(
                    id="build-program",
                    inputs={
                        "length": ComputeNodeInput(
                            kind="value",
                            value=as_value_expr(col("length")),
                        )
                    },
                    fn=build_program,
                ),
                ComputeNodeSpec(
                    id="render-waveforms",
                    output_type=Scalar(Payload("waveform_bundle")),
                    inputs={
                        "program": ComputeNodeInput(
                            kind="compute_result",
                            node_id="build-program",
                        )
                    },
                    fn=render_waveforms,
                ),
            ]
        }
    )

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameter_view()))

    assert "fn" not in spec.model_dump(mode="json")["compute_nodes"][0]
    assert [payload.id for payload in graph.payloads] == [
        "render-waveforms.payload.point-0",
    ]
    assert [
        (
            step.node_id,
            step.payload.id if step.payload is not None else None,
            step.payload.schema_id if step.payload is not None else None,
            step.dependencies.point_columns,
            step.dependencies.upstream_compute,
        )
        for step in graph.points[0].compute_steps
    ] == [
        ("build-program", None, None, ("length",), ()),
        (
            "render-waveforms",
            "render-waveforms.payload.point-0",
            "waveform_bundle",
            ("length",),
            ("build-program",),
        ),
    ]
    state_value = graph.points[0].desired_state[0].fields[0].value.root
    assert isinstance(state_value, PayloadRef)
    assert state_value.payload_id == "render-waveforms.payload.point-0"
    assert graph.payloads[0].schema_id == "waveform_bundle"
    assert graph.payloads[0].metadata["runtime_payload"] == "deferred"


def test_compute_value_inputs_support_series_and_tables_with_dependencies() -> None:
    received: dict[str, object] = {}

    def consume_collections(ctx: ComputeNodeContext) -> dict[str, int]:
        received.update(ctx.inputs)
        frequencies = ctx.inputs["frequencies"]
        rows = ctx.inputs["rows"]
        assert isinstance(frequencies, list)
        assert isinstance(rows, list)
        return {
            "frequencies": len(frequencies),
            "rows": len(rows),
        }

    node = ComputeNodeSpec(
        id="consume-collections",
        inputs={
            "frequencies": ComputeNodeInput(
                kind="value",
                value=as_value_expr(table("gate_rows").column("frequency")),
            ),
            "rows": ComputeNodeInput(
                kind="value",
                value=as_value_expr(
                    table("gate_rows")
                    .filter(col("enabled").eq(True))
                    .with_columns(offset=param("global_offset"))
                ),
            ),
            "literal_series": ComputeNodeInput(
                kind="value",
                value=as_value_expr(values([1, 2, 3])),
            ),
        },
        fn=consume_collections,
    )
    params = ParameterRelationData(
        scalars={"global_offset": Quantity(value=20.0, unit="MHz")},
        tables={
            "gate_rows": [
                {
                    "qubit": "q0",
                    "frequency": Quantity(value=5.0, unit="GHz"),
                    "enabled": True,
                },
                {
                    "qubit": "q1",
                    "frequency": Quantity(value=5.1, unit="GHz"),
                    "enabled": False,
                },
            ]
        },
    )

    results, _payloads, diagnostics = evaluate_compute_nodes_for_point(
        point=PlannerPoint(point_index=0, point_uid="point-0", row={}),
        params=params,
        compute_nodes=[node],
        route_bindings=(),
        compute_payload_schema_ids={},
    )
    dependencies = summarize_compute_node_dependencies(node)
    restored = ComputeNodeSpec.model_validate_json(node.model_dump_json())

    assert diagnostics == []
    assert results[(0, "consume-collections")] == {"frequencies": 2, "rows": 1}
    assert received["frequencies"] == [
        Quantity(value=5.0, unit="GHz"),
        Quantity(value=5.1, unit="GHz"),
    ]
    assert received["rows"] == [
        {
            "qubit": "q0",
            "frequency": Quantity(value=5.0, unit="GHz"),
            "enabled": True,
            "offset": Quantity(value=20.0, unit="MHz"),
        }
    ]
    assert received["literal_series"] == [1, 2, 3]
    assert dependencies.parameter_tables == ("gate_rows",)
    assert dependencies.scalar_params == ("global_offset",)
    assert restored.inputs["frequencies"].value is not None
    assert restored.inputs["frequencies"].value.shape == "series"
    assert restored.inputs["rows"].value is not None
    assert restored.inputs["rows"].value.shape == "table"


def test_compute_value_input_unwraps_transient_payload() -> None:
    payload = object()

    def consume_payload(ctx: ComputeNodeContext) -> bool:
        return ctx.inputs["payload"] is payload

    node = ComputeNodeSpec(
        id="consume-payload",
        inputs={
            "payload": ComputeNodeInput(
                kind="value",
                value=as_value_expr(
                    ScalarExpr(
                        kind="literal",
                        value=PayloadValue(schema_id="model", payload=payload),
                    )
                ),
            )
        },
        fn=consume_payload,
    )

    results, _payloads, diagnostics = evaluate_compute_nodes_for_point(
        point=PlannerPoint(point_index=0, point_uid="point-0", row={}),
        params=ParameterRelationData(),
        compute_nodes=[node],
        route_bindings=(),
        compute_payload_schema_ids={},
    )

    assert diagnostics == []
    assert results[(0, "consume-payload")] is True
    restored = ComputeNodeSpec.model_validate_json(node.model_dump_json())
    restored_value = restored.inputs["payload"].value
    assert restored_value is not None
    assert isinstance(restored_value, ScalarValueExpr)
    assert restored_value.expr.value == PayloadValue(schema_id="model")


def test_collection_input_references_are_tracked_as_compute_dependencies() -> None:
    node = ComputeNodeSpec(
        id="external-collections",
        inputs={
            "offsets": ComputeNodeInput(
                kind="value",
                value=as_value_expr(input_series("offsets")),
            ),
            "rows": ComputeNodeInput(
                kind="value",
                value=as_value_expr(input_table("rows")),
            ),
        },
    )

    assert summarize_compute_node_dependencies(node).input_refs == ("offsets", "rows")


def test_runtime_graph_keeps_generated_payloads_deferred() -> None:
    class WaveformPayload:
        def __init__(self, samples: list[float]) -> None:
            self.samples = samples

    def build_waveform(ctx: ComputeNodeContext) -> WaveformPayload:
        return WaveformPayload(samples=[0.0, 0.5, 0.0])

    spec = experiment(
        id="in-memory-waveform-plan",
        kind="diagnostic",
        points=grid(index=[0]),
        state=[
            set_state(
                "drive-a",
                "play_waveforms.program",
                compute_result("build-waveform"),
            )
        ],
        records=[],
    ).model_copy(
        update={
            "compute_nodes": [
                ComputeNodeSpec(
                    id="build-waveform",
                    output_type=Scalar(Payload("pulse_program")),
                    fn=build_waveform,
                )
            ]
        }
    )

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameter_view()))

    assert graph.payloads[0].uri is None
    assert graph.payloads[0].content_hash is None
    assert not isinstance(graph.payloads[0].payload, WaveformPayload)
    assert graph.payloads[0].metadata["runtime_payload"] == "deferred"


def test_runtime_graph_deduplicates_repeated_state_fields() -> None:
    spec = experiment(
        id="dedupe-state-fields",
        kind="diagnostic",
        points=grid(index=[0]),
        state=[
            set_state("drive-a", "pulse.frequency", 5.0),
            set_state("drive-a", "pulse.frequency", 5.0),
        ],
        records=[],
    )

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameter_view()))

    assert [diagnostic["code"] for diagnostic in graph.diagnostics] == []
    assert len(graph.points[0].desired_state) == 1
    assert len(graph.points[0].desired_state[0].fields) == 1
    assert graph.points[0].desired_state[0].fields[0].field_path == ("frequency")


def test_runtime_graph_reports_conflicting_normalized_state_fields() -> None:
    spec = experiment(
        id="conflicting-state-fields",
        kind="diagnostic",
        points=grid(index=[0]),
        state=[
            set_state("drive-a", "pulse.frequency", 5.0),
            set_state("drive-a", "pulse.frequency", 5.1),
        ],
        records=[],
    )

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameter_view()))

    assert "runtime_state_field_conflict" in {
        diagnostic["code"] for diagnostic in graph.diagnostics
    }
    assert len(graph.points[0].desired_state) == 1
    assert len(graph.points[0].desired_state[0].fields) == 1


def test_compute_node_specs_round_trip_without_source_callable() -> None:
    def build_waveform(ctx: ComputeNodeContext) -> dict[str, int]:
        return {"point": ctx.point_index}

    spec = experiment(
        id="persisted-program-node-plan",
        kind="diagnostic",
        points=grid(index=[0]),
        state=[
            set_state(
                "drive-a",
                "play_waveforms.program",
                compute_result("build-waveform"),
            )
        ],
        records=[],
    ).model_copy(
        update={
            "compute_nodes": [
                ComputeNodeSpec(
                    id="build-waveform",
                    output_type=Scalar(Payload("pulse_program")),
                    fn=build_waveform,
                )
            ]
        }
    )

    restored = ExperimentSpec.model_validate_json(spec.model_dump_json())
    plan = build_planner_snapshot(restored, _parameter_view())
    graph = build_runtime_graph(plan)
    _results, _payloads, diagnostics = evaluate_compute_nodes_for_point(
        point=PlannerPoint(
            point_index=graph.points[0].point_index,
            point_uid=graph.points[0].point_uid,
            row=graph.points[0].row,
        ),
        params=graph.points[0].params,
        compute_nodes=list(graph.compute_nodes_by_id.values()),
        route_bindings=graph.points[0].route_bindings,
        compute_payload_schema_ids={
            step.node_id: step.payload.schema_id
            for step in graph.points[0].compute_steps
            if step.payload is not None
        },
    )

    assert restored.compute_nodes[0].fn is None
    assert restored.state[0].value == ComputeResultRef(node_id="build-waveform")
    assert plan.points[0].point_index == 0
    assert diagnostics[0]["code"] == "compute_node_evaluation_failed"
    assert "no in-memory function" in diagnostics[0]["message"]

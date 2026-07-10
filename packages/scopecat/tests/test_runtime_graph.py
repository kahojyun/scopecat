import pytest
from pydantic import ValidationError

from scopecat._compiler.program import (
    ComputeNodeInput,
    ComputeNodeSpec,
    compute_result,
    observable,
    set_state,
)
from scopecat._compiler.program import (
    linked_program as experiment,
)
from scopecat._planning.compute_dependencies import (
    summarize_compute_node_dependencies,
)
from scopecat._planning.planner import PlannerPoint, build_planner_snapshot
from scopecat._planning.state import StateRecord, StateSpec
from scopecat._relations import (
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
from scopecat._runtime.graph import build_runtime_graph
from scopecat._runtime.lowering import (
    compile_desired_state_points,
    evaluate_compute_nodes_for_point,
)
from scopecat._runtime.models import PointRouteBinding
from scopecat._value_expressions import (
    ScalarValueExpr,
    as_value_expr,
)
from scopecat.authoring.values import ResolvedRoute
from scopecat.models.config import RoutingChannelBinding
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity
from scopecat.models.state import PayloadRef
from scopecat.models.value import PayloadValue
from scopecat.value_types import (
    Bool,
    Float,
    Int,
    Payload,
    Route,
    Scalar,
    Series,
    String,
)
from scopecat.value_types import (
    Quantity as QuantityType,
)
from scopecat.value_types import (
    Table as TableType,
)
from tests.support.parameter_fixtures import (
    parameters as _parameters,
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

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameters()))

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
    assert entity_kind_state.evaluate(
        point_index=0,
        ctx=EvalContext(),
    )[0].route_entities == [EntityRef(id="q0", kind="input")]
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


def test_compute_result_state_refs_keep_producer_output_types() -> None:
    ref = compute_result("build-waveform")
    state = set_state("drive-a", "play_waveforms.program", ref)

    assert state.value == ref

    spec = experiment(
        id="typed-compute-payload",
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
    assert spec.state[0].value == ref
    assert spec.compute_nodes[0].output_type == Scalar(Payload("pulse_program"))


def test_compute_input_requires_a_declared_value_type() -> None:
    with pytest.raises(ValidationError, match="value_type"):
        ComputeNodeInput.model_validate(
            {
                "kind": "value",
                "value": as_value_expr(lit("untyped")),
            }
        )


def test_compute_node_requires_a_declared_output_type() -> None:
    with pytest.raises(ValidationError, match="output_type"):
        ComputeNodeSpec.model_validate({"id": "untyped"})


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
    ).model_copy(
        update={
            "compute_nodes": [
                ComputeNodeSpec(
                    id="build-waveform",
                    output_type=Scalar(Payload("unused-waveform")),
                )
            ]
        }
    )

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameters()))

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

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameters()))

    assert "compute_payload_unknown_node" in {
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

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameters()))

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

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameters()))

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
    plan = build_planner_snapshot(spec, _parameters())

    graph = build_runtime_graph(plan)

    assert graph.experiment_id == spec.id
    assert graph.point_count == 1
    assert graph.expected_measurement_indices == {0}
    assert [point.point_index for point in graph.points] == [0]
    assert [binding.record_id for binding in graph.product_bindings] == ["signal"]
    assert "schema_version" not in graph.__dict__
    assert "content_hash" not in graph.__dict__


def test_runtime_graph_evaluates_generated_payload_nodes() -> None:
    def build_program(*, length: object) -> dict[str, object]:
        assert length == Quantity(value=20.0, unit="ns")
        return {"length": length}

    def render_waveforms(*, program: object) -> dict[str, object]:
        assert isinstance(program, dict)
        return {"source_program": program["length"], "samples": [0.0, 0.5, 0.0]}

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
                    output_type=Scalar(Payload("program")),
                    inputs={
                        "length": ComputeNodeInput(
                            kind="value",
                            value=as_value_expr(col("length")),
                            value_type=Scalar(QuantityType()),
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
                            value_type=Scalar(Payload("program")),
                        )
                    },
                    fn=render_waveforms,
                ),
            ]
        }
    )

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameters()))

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

    def consume_collections(
        *,
        frequencies: object,
        rows: object,
        literal_series: object,
    ) -> dict[str, int]:
        received.update(
            frequencies=frequencies,
            rows=rows,
            literal_series=literal_series,
        )
        assert isinstance(frequencies, list)
        assert isinstance(rows, list)
        return {
            "frequencies": len(frequencies),
            "rows": len(rows),
        }

    node = ComputeNodeSpec(
        id="consume-collections",
        output_type=Scalar(Payload("collection-counts")),
        inputs={
            "frequencies": ComputeNodeInput(
                kind="value",
                value=as_value_expr(table("gate_rows").column("frequency")),
                value_type=Series(Scalar(QuantityType())),
            ),
            "rows": ComputeNodeInput(
                kind="value",
                value=as_value_expr(
                    table("gate_rows")
                    .filter(col("enabled").eq(True))
                    .with_columns(offset=param("global_offset"))
                ),
                value_type=TableType(columns=(), allow_extra_columns=True),
            ),
            "literal_series": ComputeNodeInput(
                kind="value",
                value=as_value_expr(values([1, 2, 3])),
                value_type=Series(Scalar(Int())),
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
    assert dependencies.parameters == ("gate_rows", "global_offset")
    assert node.inputs["frequencies"].value is not None
    assert node.inputs["frequencies"].value.shape == "series"
    assert node.inputs["rows"].value is not None
    assert node.inputs["rows"].value.shape == "table"


def test_compute_value_input_unwraps_transient_payload() -> None:
    expected_payload = object()

    def consume_payload(*, payload: object) -> bool:
        return payload is expected_payload

    node = ComputeNodeSpec(
        id="consume-payload",
        output_type=Scalar(Bool()),
        inputs={
            "payload": ComputeNodeInput(
                kind="value",
                value=as_value_expr(
                    ScalarExpr(
                        kind="literal",
                        value=PayloadValue(
                            schema_id="model",
                            payload=expected_payload,
                        ),
                    )
                ),
                value_type=Scalar(Payload("model")),
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
    value = node.inputs["payload"].value
    assert value is not None
    assert isinstance(value, ScalarValueExpr)
    assert value.expr.value == PayloadValue(
        schema_id="model",
        payload=expected_payload,
    )


def test_compute_named_context_receives_only_its_declared_input() -> None:
    node = ComputeNodeSpec(
        id="ordinary-context-input",
        output_type=Scalar(String()),
        inputs={
            "context": ComputeNodeInput(
                kind="value",
                value=as_value_expr(lit("declared")),
                value_type=Scalar(String()),
            )
        },
        fn=lambda *, context: context,
    )

    results, _payloads, diagnostics = evaluate_compute_nodes_for_point(
        point=PlannerPoint(point_index=0, point_uid="point-0", row={}),
        params=ParameterRelationData(),
        compute_nodes=[node],
        route_bindings=(),
        compute_payload_schema_ids={},
    )

    assert diagnostics == []
    assert results[(0, "ordinary-context-input")] == "declared"


def test_compute_route_is_an_explicit_input_and_dependency() -> None:
    received: list[ResolvedRoute] = []

    def consume_route(*, drive_route: ResolvedRoute) -> str:
        received.append(drive_route)
        return drive_route.resource_id

    node = ComputeNodeSpec(
        id="route-consumer",
        output_type=Scalar(String()),
        inputs={
            "drive_route": ComputeNodeInput(
                kind="route",
                port_id="drive",
                value_type=Route(capabilities=("play",)),
            )
        },
        fn=consume_route,
    )
    route = PointRouteBinding(
        port_id="drive",
        resource_id="drive-a",
        capabilities=["play"],
        entity_ids=["q0"],
        product_axis_order=["q0"],
    )

    results, _payloads, diagnostics = evaluate_compute_nodes_for_point(
        point=PlannerPoint(point_index=0, point_uid="point-0", row={}),
        params=ParameterRelationData(),
        compute_nodes=[node],
        route_bindings=(route,),
        compute_payload_schema_ids={},
    )

    assert diagnostics == []
    assert results[(0, "route-consumer")] == "drive-a"
    assert received == [
        ResolvedRoute(
            port_id="drive",
            resource_id="drive-a",
            capabilities=("play",),
            entity_ids=("q0",),
            product_axis_order=("q0",),
        )
    ]
    assert summarize_compute_node_dependencies(node).routes == ("drive",)


def test_compute_result_must_satisfy_its_declared_value_type() -> None:
    node = ComputeNodeSpec(
        id="invalid-series",
        output_type=Series(Scalar(Float())),
        fn=lambda: ["not-a-float"],
    )

    results, _payloads, diagnostics = evaluate_compute_nodes_for_point(
        point=PlannerPoint(point_index=0, point_uid="point-0", row={}),
        params=ParameterRelationData(),
        compute_nodes=[node],
        route_bindings=(),
        compute_payload_schema_ids={},
    )

    assert results == {}
    assert diagnostics[0]["code"] == "compute_node_evaluation_failed"
    assert "expected float" in diagnostics[0]["message"]


def test_collection_input_references_are_tracked_as_compute_dependencies() -> None:
    node = ComputeNodeSpec(
        id="external-collections",
        output_type=Scalar(Payload("unused-collections")),
        inputs={
            "offsets": ComputeNodeInput(
                kind="value",
                value=as_value_expr(input_series("offsets")),
                value_type=Series(Scalar(Float())),
            ),
            "rows": ComputeNodeInput(
                kind="value",
                value=as_value_expr(input_table("rows")),
                value_type=TableType(columns=(), allow_extra_columns=True),
            ),
        },
    )

    assert summarize_compute_node_dependencies(node).input_refs == ("offsets", "rows")


def test_runtime_graph_keeps_generated_payloads_deferred() -> None:
    class WaveformPayload:
        def __init__(self, samples: list[float]) -> None:
            self.samples = samples

    def build_waveform() -> WaveformPayload:
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

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameters()))

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

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameters()))

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

    graph = build_runtime_graph(build_planner_snapshot(spec, _parameters()))

    assert "runtime_state_field_conflict" in {
        diagnostic["code"] for diagnostic in graph.diagnostics
    }
    assert len(graph.points[0].desired_state) == 1
    assert len(graph.points[0].desired_state[0].fields) == 1

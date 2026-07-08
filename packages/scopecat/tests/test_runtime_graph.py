from scopecat._planning.planner import PlannerPoint, build_planner_snapshot
from scopecat._runtime.graph import build_runtime_graph
from scopecat._runtime.lowering import evaluate_compute_nodes_for_point
from scopecat.experiments import (
    ComputeNodeContext,
    ComputeNodeInput,
    ComputeNodeSpec,
    ExperimentSpec,
    experiment,
    observable,
    set_state,
)
from scopecat.models.parameter import Quantity
from scopecat.relations import (
    col,
    grid,
)
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
                {
                    "kind": "compute_result",
                    "node_id": "render-waveforms",
                    "payload_kind": "waveform_bundle",
                },
            )
        ],
        records=[],
    ).model_copy(
        update={
            "compute_nodes": [
                ComputeNodeSpec(
                    id="build-program",
                    inputs={
                        "length": ComputeNodeInput(kind="value", value=col("length"))
                    },
                    fn=build_program,
                ),
                ComputeNodeSpec(
                    id="render-waveforms",
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
            step.payload_id,
            step.payload_kind,
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
    assert graph.points[0].desired_state[0].fields[0].value.payload_id == (
        "render-waveforms.payload.point-0"
    )
    assert graph.payloads[0].kind == "waveform_bundle"
    assert graph.payloads[0].metadata["runtime_payload"] == "deferred"


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
                {
                    "kind": "compute_result",
                    "node_id": "build-waveform",
                    "payload_kind": "pulse_program",
                },
            )
        ],
        records=[],
    ).model_copy(
        update={
            "compute_nodes": [
                ComputeNodeSpec(
                    id="build-waveform",
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
                {
                    "kind": "compute_result",
                    "node_id": "build-waveform",
                    "payload_kind": "pulse_program",
                },
            )
        ],
        records=[],
    ).model_copy(
        update={
            "compute_nodes": [
                ComputeNodeSpec(
                    id="build-waveform",
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
        compute_payload_kinds={
            step.node_id: step.payload_kind
            for step in graph.points[0].compute_steps
            if step.payload_kind is not None
        },
    )

    assert restored.compute_nodes[0].fn is None
    assert plan.points[0].point_index == 0
    assert diagnostics[0]["code"] == "compute_node_evaluation_failed"
    assert "no in-memory function" in diagnostics[0]["message"]

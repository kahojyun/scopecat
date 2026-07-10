from __future__ import annotations

import json
from pathlib import Path

from scopecat._runtime.evidence import instrument_state_evidence_ref
from scopecat._runtime.executor import execute_run
from scopecat.experiments import (
    ComputeNodeContext,
    ComputeNodeInput,
    ComputeNodeSpec,
    ExperimentSpec,
    as_value_expr,
    compute_result,
    experiment,
    observable,
    set_state,
)
from scopecat.instruments import (
    RuntimeEvent,
    RuntimePayloadObservation,
)
from scopecat.instruments.sdk import (
    CapabilityDescription,
    CapabilityField,
    CommandChannelBinding,
    InstrumentDescription,
    InstrumentStateCommand,
    InstrumentStateCommandField,
    InstrumentStateField,
    InstrumentStateSnapshot,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.execution import InstrumentStateEvidence
from scopecat.models.parameter import Quantity
from scopecat.models.run import RunManifest
from scopecat.models.state import StateValue
from scopecat.relations import col, grid
from scopecat.runs import dataset_storage_ref
from scopecat.value_types import Payload, Scalar
from scopecat.value_types import Quantity as QuantityType
from tests.support.instrument_drivers import SignalInstrumentDriver
from tests.support.records import (
    assert_model_round_trip,
    read_measurement_records,
    read_model,
)
from tests.support.signal_instruments import (
    TestSignalInstrument,
)
from tests.support.workflow_fixtures import load_config, load_experiment


def test_instrument_models_round_trip() -> None:
    description = InstrumentDescription(
        instrument_id="source-0",
        implementation_id="test.instrument",
        implementation_version="v1",
        capabilities=[
            CapabilityDescription(
                id="set_frequency",
                fields=[
                    CapabilityField(
                        id="frequency",
                        value_type=Scalar(QuantityType(unit="GHz")),
                    )
                ],
            )
        ],
    )
    state_value = StateValue(Quantity(value=5.0, unit="GHz"))
    state = InstrumentStateSnapshot(
        instrument_id="source-0",
        fields=[
            InstrumentStateField(
                capability_id="set_frequency",
                field_path="frequency",
                value=state_value,
            )
        ],
    )
    command = InstrumentStateCommand(
        instrument_id="source-0",
        fields=[
            InstrumentStateCommandField(
                resource_id="source-0",
                capability_id="set_frequency",
                field_path="frequency",
                value=state_value,
                channel_bindings=[
                    CommandChannelBinding(
                        entity_id="q0",
                        channel_id="drive.awg0.ch1",
                        line_id="q0.xy",
                        capability="set_frequency",
                        group_ids=["lo.xy0"],
                    )
                ],
            )
        ],
    )

    assert_model_round_trip(
        description,
        schema_version="scopecat.instrument_description.v1",
    )
    assert_model_round_trip(
        state,
        schema_version="scopecat.instrument_state_snapshot.v1",
    )
    assert_model_round_trip(
        command,
        schema_version="scopecat.instrument_state_command.v2",
    )


def test_execute_run_persists_measurements_and_run_files(
    tmp_path: Path,
) -> None:
    config = load_config()
    manifest, summary = execute_run(
        config=config,
        experiment=load_experiment(),
        instruments=[TestSignalInstrument()],
        workspace=tmp_path,
    )

    run_dir = tmp_path / "runs" / manifest.run_id
    assert manifest.status == "completed"
    assert {record.id for record in manifest.records} == {
        "execution-summary",
        "instrument-state-evidence",
    }
    assert {dataset.id for dataset in manifest.datasets} == {"raw-measurements"}
    raw_dataset = manifest.datasets[0]
    assert raw_dataset.kind == "measurement_dataset"
    assert summary.experiment_id == load_experiment().id
    assert summary.instrument_ids == ["source-0"]
    assert summary.point_count == 3
    assert summary.completed_point_count == 3
    assert summary.measurement_count == 3
    assert summary.state.changed_field_count == 3
    assert summary.state.skipped_field_count == 0
    assert summary.state.state_command_count == 3
    assert summary.compute.evaluated_node_count == 0
    assert summary.compute.reused_node_count == 0
    assert summary.compute.payload_count == 0

    persisted_manifest = read_model(run_dir / "manifest.json", RunManifest)
    persisted_config = read_model(
        run_dir / "config-profile.snapshot.json",
        ConfigProfileSnapshot,
    )
    persisted_experiment = read_model(run_dir / "experiment-spec.json", ExperimentSpec)
    state_evidence_path = run_dir / instrument_state_evidence_ref()
    state_evidence = read_model(state_evidence_path, InstrumentStateEvidence)
    assert persisted_manifest == manifest
    assert persisted_config == config
    assert persisted_experiment.id == summary.experiment_id
    assert persisted_experiment.schema_version == "scopecat.experiment_spec.v7"
    assert state_evidence.schema_version == "scopecat.instrument_state_evidence.v2"
    assert {
        snapshot.schema_version
        for snapshot in [*state_evidence.initial_state, *state_evidence.final_state]
    } == {"scopecat.instrument_state_snapshot.v1"}
    final_state_value = state_evidence.final_state[0].fields[0].value.root
    assert final_state_value == Quantity(value=5.1, unit="GHz")
    persisted_state_evidence = json.loads(state_evidence_path.read_text())
    assert persisted_state_evidence["final_state"][0]["fields"][0]["value"] == {
        "value": 5.1,
        "unit": "GHz",
    }
    assert not (run_dir / "experiment-plan.json").exists()
    assert not (run_dir / "records" / "device_program" / "device-program.json").exists()

    measurements = read_measurement_records(run_dir / dataset_storage_ref(raw_dataset))
    assert [item.point_index for item in measurements] == [0, 1, 2]
    drive_frequencies: list[float] = []
    for item in measurements:
        drive_frequency = item.coordinates["drive_frequency"]
        assert isinstance(drive_frequency, Quantity)
        drive_frequencies.append(drive_frequency.value)
    assert drive_frequencies == [
        4.9,
        5.0,
        5.1,
    ]
    signal_values: list[float] = []
    for measurement in measurements:
        signal = measurement.observables["signal"]
        assert isinstance(signal, Quantity)
        signal_values.append(signal.value)
    assert signal_values == [
        0.5,
        1.0,
        0.5,
    ]


def test_execute_run_emits_transient_runtime_events(tmp_path: Path) -> None:
    events: list[RuntimeEvent] = []

    manifest, summary = execute_run(
        config=load_config(),
        experiment=load_experiment(),
        instruments=[TestSignalInstrument()],
        workspace=tmp_path,
        event_sink=events.append,
    )

    assert manifest.status == "completed"
    assert summary.completed_point_count == 3
    lifecycle_events = [
        event.kind for event in events if event.kind in {"run_started", "run_finished"}
    ]
    assert lifecycle_events == [
        "run_started",
        "run_finished",
    ]
    assert [event.kind for event in events].count("point_started") == 3
    assert [event.kind for event in events].count("record_emitted") == 3
    point_events = [event for event in events if event.kind == "point_started"]
    assert [event.summary["compute_step_count"] for event in point_events] == [0, 0, 0]
    assert events[-1].summary["status"] == "completed"
    assert events[-1].progress == {"completed_points": 3, "total_points": 3}


def test_execute_run_reuses_unchanged_compute_payloads(tmp_path: Path) -> None:
    calls: list[int] = []

    def build_program(ctx: ComputeNodeContext) -> dict[str, object]:
        value = ctx.inputs["value"]
        assert isinstance(value, int)
        calls.append(value)
        return {"value": value}

    spec = experiment(
        id="cached-compute-run",
        kind="diagnostic",
        points=grid(value=[1, 1, 2]),
        state=[
            set_state(
                "source-0",
                "play_program.program",
                compute_result("build-program"),
            )
        ],
        records=[observable("signal", resource="source-0")],
    ).model_copy(
        update={
            "compute_nodes": [
                ComputeNodeSpec(
                    id="build-program",
                    output_type=Scalar(Payload("pulse_program")),
                    inputs={
                        "value": ComputeNodeInput(
                            kind="value",
                            value=as_value_expr(col("value")),
                        )
                    },
                    fn=build_program,
                )
            ]
        }
    )
    events: list[RuntimeEvent] = []
    payload_observations: list[RuntimePayloadObservation] = []

    manifest, summary = execute_run(
        config=load_config(),
        experiment=spec,
        instruments=[SignalInstrumentDriver()],
        workspace=tmp_path,
        event_sink=events.append,
        payload_observer=payload_observations.append,
    )

    compute_events = [event for event in events if event.kind == "compute_finished"]
    state_events = [event for event in events if event.kind == "state_applied"]

    assert manifest.status == "completed"
    assert calls == [1, 2]
    assert [event.summary["compute_status"] for event in compute_events] == [
        "evaluated",
        "reused",
        "evaluated",
    ]
    assert [event.summary["payload_id"] for event in compute_events] == [
        "build-program.payload.point-0",
        "build-program.payload.point-1",
        "build-program.payload.point-2",
    ]
    assert [
        (observation.payload_id, observation.compute_status)
        for observation in payload_observations
    ] == [
        ("build-program.payload.point-0", "evaluated"),
        ("build-program.payload.point-1", "reused"),
        ("build-program.payload.point-2", "evaluated"),
    ]
    assert [observation.payload.payload for observation in payload_observations] == [
        {"value": 1},
        {"value": 1},
        {"value": 2},
    ]
    assert payload_observations[0].summary["payload_id"] == (
        "build-program.payload.point-0"
    )
    assert [
        event.summary["compute_evaluated_node_count"] for event in state_events
    ] == [1, 0, 1]
    assert [event.summary["compute_reused_node_count"] for event in state_events] == [
        0,
        1,
        0,
    ]
    assert summary.compute.evaluated_node_count == 2
    assert summary.compute.reused_node_count == 1
    assert summary.compute.payload_count == 3
    assert summary.state.payload_count == 3
    assert events[-1].summary["compute_evaluated_node_count"] == 2
    assert events[-1].summary["compute_reused_node_count"] == 1
    assert events[-1].summary["compute_payload_count"] == 3


def test_execute_run_skips_unchanged_state_fields(tmp_path: Path) -> None:
    instrument = TestSignalInstrument()
    experiment = load_experiment().model_copy(
        update={
            "state": [
                set_state(
                    "source-0",
                    "set_frequency.frequency",
                    Quantity(value=5.9, unit="GHz"),
                )
            ]
        }
    )
    events: list[RuntimeEvent] = []

    manifest, summary = execute_run(
        config=load_config(),
        experiment=experiment,
        instruments=[instrument],
        workspace=tmp_path,
        event_sink=events.append,
    )

    assert manifest.status == "completed"
    assert len(instrument.applied_commands) == 1
    assert summary.state.changed_field_count == 1
    assert summary.state.skipped_field_count == 2
    assert summary.state.state_command_count == 1
    state_events = [event for event in events if event.kind == "state_applied"]
    assert [event.summary["changed_field_count"] for event in state_events] == [
        1,
        0,
        0,
    ]
    assert [event.summary["skipped_field_count"] for event in state_events] == [
        0,
        1,
        1,
    ]

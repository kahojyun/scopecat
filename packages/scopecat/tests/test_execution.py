from __future__ import annotations

from pathlib import Path

from scopecat.experiments import (
    PlanSnapshot,
)
from scopecat.instruments import execute_run
from scopecat.instruments.sdk import (
    CapabilityDescription,
    CapabilityField,
    InstrumentDescription,
    InstrumentStateField,
    InstrumentStatePatch,
    InstrumentStateSnapshot,
)
from scopecat.instruments.state import (
    StatePatchField,
    StateValue,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.models.run import RunManifest
from tests.support.records import (
    assert_artifact_ref,
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
                fields=[CapabilityField(id="frequency", kind="quantity", unit="GHz")],
            )
        ],
    )
    state_value = StateValue(
        kind="quantity",
        quantity=Quantity(value=5.0, unit="GHz"),
    )
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
    patch = InstrumentStatePatch(
        instrument_id="source-0",
        fields=[
            StatePatchField(
                resource_id="source-0",
                capability_id="set_frequency",
                field_path="frequency",
                after=state_value,
            )
        ],
    )

    assert_model_round_trip(description)
    assert_model_round_trip(state)
    assert_model_round_trip(patch)


def test_execute_run_persists_measurements_and_run_files(
    tmp_path: Path,
) -> None:
    config = load_config()
    manifest, snapshot = execute_run(
        config=config,
        experiment=load_experiment(),
        instruments=[TestSignalInstrument()],
        workspace=tmp_path,
    )

    run_dir = tmp_path / "runs" / manifest.run_id
    assert manifest.status == "completed"
    assert {artifact.id for artifact in manifest.artifact_refs} == {
        "execution-snapshot",
        "raw-measurements",
    }
    raw_artifact = assert_artifact_ref(
        manifest.artifact_refs,
        "raw-measurements",
        kind="measurement_dataset",
        path="artifacts/raw-measurements.jsonl",
    )
    assert raw_artifact.path == "artifacts/raw-measurements.jsonl"
    assert snapshot.experiment_id == load_experiment().id
    assert snapshot.instrument_ids == ["source-0"]
    assert snapshot.measurement_count == 3
    assert [point.changed_field_count for point in snapshot.points] == [1, 1, 1]
    assert [point.acquired_record_count for point in snapshot.points] == [1, 1, 1]

    persisted_manifest = read_model(run_dir / "manifest.json", RunManifest)
    persisted_config = read_model(
        run_dir / "config-profile.snapshot.json",
        ConfigProfileSnapshot,
    )
    persisted_plan = read_model(run_dir / "plan.snapshot.json", PlanSnapshot)
    assert (run_dir / "artifacts" / "execution.snapshot.json").is_file()
    assert (run_dir / "artifacts" / "raw-measurements.jsonl").is_file()
    assert persisted_manifest == manifest
    assert persisted_config == config
    assert persisted_plan.schema_version == "scopecat.plan_snapshot.v1"
    assert persisted_plan.experiment_id == snapshot.experiment_id
    assert len(persisted_plan.points) == snapshot.point_count

    measurements = read_measurement_records(
        run_dir / "artifacts" / "raw-measurements.jsonl"
    )
    assert [item.point_index for item in measurements] == [0, 1, 2]
    assert [item.coordinates["drive_frequency"].value for item in measurements] == [
        4.9,
        5.0,
        5.1,
    ]
    assert [item.observables["signal"].value for item in measurements] == [
        0.5,
        1.0,
        0.5,
    ]

from __future__ import annotations

from pathlib import Path

from scopecat.experiments import (
    PlanSnapshot,
)
from scopecat.instruments import (
    NativeBoundaryManifest,
    execute_native_run,
)
from scopecat.instruments.sdk import (
    CapabilityDescription,
    CapabilityField,
    InstrumentDescription,
    InstrumentStateField,
    InstrumentStatePatch,
    InstrumentStateSnapshot,
    NativeInstrumentProviderContext,
    NativeInstrumentProviderResult,
)
from scopecat.instruments.state import (
    StatePatchField,
    StateValue,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.models.run import RunManifest
from tests.support.native_signal import (
    TestSignalInstrument,
    TestSignalInstrumentProvider,
)
from tests.support.records import (
    assert_artifact_ref,
    assert_model_round_trip,
    read_measurement_records,
    read_model,
)
from tests.support.workflow_fixtures import load_config, load_experiment


def test_native_instrument_models_round_trip() -> None:
    description = InstrumentDescription(
        instrument_id="source-0",
        implementation_id="test.native",
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


def test_test_signal_provider_constructs_fresh_config_selected_instruments() -> None:
    provider = TestSignalInstrumentProvider()
    context = NativeInstrumentProviderContext(
        config=load_config(),
        experiment=load_experiment(),
    )
    first = provider.provide(context)
    second = provider.provide(context)

    assert isinstance(first, NativeInstrumentProviderResult)
    assert first.diagnostics == ()
    assert second.diagnostics == ()
    assert first.instruments[0].instrument_id == "source-0"
    assert second.instruments[0].instrument_id == "source-0"
    assert first.instruments[0] is not second.instruments[0]


def test_execute_native_run_persists_measurements_and_run_files(
    tmp_path: Path,
) -> None:
    config = load_config()
    manifest, snapshot = execute_native_run(
        config=config,
        experiment=load_experiment(),
        instruments=[TestSignalInstrument()],
        workspace=tmp_path,
    )

    run_dir = tmp_path / "runs" / manifest.run_id
    assert manifest.status == "completed"
    assert manifest.runner_id == "scopecat.native"
    assert manifest.dry_run is False
    assert manifest.runner_versions == {"tests.signal_instrument": "v0"}
    assert {artifact.id for artifact in manifest.artifact_refs} == {
        "native-run-boundary",
        "native-run-snapshot",
        "native-run-summary",
        "raw-measurements",
    }
    raw_artifact = assert_artifact_ref(
        manifest.artifact_refs,
        "raw-measurements",
        kind="measurement_dataset",
        path="artifacts/raw-measurements.jsonl",
    )
    assert raw_artifact.path == snapshot.data_ref
    assert snapshot.runner_id == "scopecat.native"
    assert snapshot.instrument_ids == ["source-0"]
    assert snapshot.measurement_count == 3
    assert snapshot.data_ref == "artifacts/raw-measurements.jsonl"
    assert [point.changed_field_count for point in snapshot.points] == [1, 1, 1]
    assert [point.acquired_record_count for point in snapshot.points] == [1, 1, 1]

    persisted_manifest = read_model(run_dir / "manifest.json", RunManifest)
    persisted_config = read_model(
        run_dir / "config-profile.snapshot.json",
        ConfigProfileSnapshot,
    )
    assert (run_dir / "plan.snapshot.json").is_file()
    assert (run_dir / "events.jsonl").is_file()
    assert (run_dir / "artifacts" / "native-run.summary.md").is_file()
    assert (run_dir / "artifacts" / "native-run.snapshot.json").is_file()
    assert (run_dir / "artifacts" / "native-run.boundary.json").is_file()
    assert (run_dir / "artifacts" / "raw-measurements.jsonl").is_file()
    assert persisted_manifest == manifest
    assert persisted_config == config
    boundary = read_model(
        run_dir / "artifacts" / "native-run.boundary.json",
        NativeBoundaryManifest,
    )
    assert boundary.schema_version == "scopecat.native_boundary_manifest.v1"
    assert boundary.run_id == manifest.run_id
    assert boundary.status == "completed"
    assert boundary.runner_id == "scopecat.native"
    assert boundary.instrument_ids == ["source-0"]
    assert boundary.plan_schema_version == snapshot.plan.schema_version
    assert boundary.plan_content_hash == snapshot.plan.content_hash
    assert boundary.config_profile_ref == manifest.config_profile_snapshot_ref
    assert boundary.plan_ref == manifest.plan_snapshot_ref
    assert boundary.desired_state_count == len(snapshot.plan.desired_state)
    assert boundary.state_patch_count == len(snapshot.plan.state_patches)
    assert boundary.acquisition_kind == snapshot.plan.acquisition.kind
    assert boundary.acquisition_record == snapshot.plan.acquisition.record
    assert boundary.result_intent_count == len(snapshot.plan.result_intents)
    assert boundary.expected_dataset_schema_id == (
        snapshot.plan.expected_dataset_schema.dataset_id
        if snapshot.plan.expected_dataset_schema is not None
        else None
    )
    assert boundary.measurement_dataset_ref == snapshot.data_ref
    assert boundary.event_count == 5
    assert boundary.point_count == snapshot.point_count
    assert boundary.measurement_count == snapshot.measurement_count
    assert boundary.diagnostics == snapshot.diagnostics
    assert boundary.metadata == snapshot.metadata

    measurements = read_measurement_records(
        run_dir / "artifacts" / "raw-measurements.jsonl"
    )
    assert [item.point_index for item in measurements] == [0, 1, 2]
    assert [item.observables["signal"].value for item in measurements] == [
        0.5,
        1.0,
        0.5,
    ]


def test_execute_native_run_persists_plan_snapshot(tmp_path: Path) -> None:
    manifest, snapshot = execute_native_run(
        config=load_config(),
        experiment=load_experiment(),
        instruments=[TestSignalInstrument()],
        workspace=tmp_path,
    )

    run_dir = tmp_path / "runs" / manifest.run_id
    persisted_plan = read_model(run_dir / "plan.snapshot.json", PlanSnapshot)
    measurements = read_measurement_records(
        run_dir / "artifacts" / "raw-measurements.jsonl"
    )

    assert manifest.status == "completed"
    assert manifest.runner_id == "scopecat.native"
    assert snapshot.plan.schema_version == "scopecat.plan_snapshot.v1"
    assert snapshot.point_count == 3
    assert snapshot.measurement_count == 3
    assert [point.changed_field_count for point in snapshot.points] == [1, 1, 1]
    assert persisted_plan == snapshot.plan
    assert persisted_plan.schema_version == "scopecat.plan_snapshot.v1"
    assert [item.coordinates["drive_frequency"].value for item in measurements] == [
        4.9,
        5.0,
        5.1,
    ]

from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.errors import ValidationFailed
from scopecat.experiments import PlanSnapshot
from scopecat.models.config import (
    ConfigProfileSnapshot,
)
from scopecat.models.run import RunEvent, RunManifest
from scopecat.runner import (
    RunnerAdapterBoundaryManifest,
    execute_runner_adapter,
)
from scopecat.runs import open_run_store
from tests.support.records import (
    read_jsonl_models,
    read_measurement_records,
    read_model,
    require_artifact,
)
from tests.support.runner_adapter import (
    ArtifactRunnerAdapter,
    FailingAfterArtifactRunnerAdapter,
    FakeRunnerAdapter,
    KernelRunnerAdapter,
    assert_measurement_dataset_schema,
    load_config,
    load_simulated_config,
)
from tests.support.workflow_fixtures import load_experiment


def test_execute_runner_adapter_persists_measurements_and_run_files(
    tmp_path: Path,
) -> None:
    config = load_config()
    manifest, snapshot = execute_runner_adapter(
        config=config,
        experiment=load_experiment(),
        adapter=FakeRunnerAdapter(),
        workspace=tmp_path,
    )

    run_dir = tmp_path / "runs" / manifest.run_id
    assert manifest.status == "completed"
    assert manifest.runner_id == "test.runner_adapter"
    assert manifest.dry_run is False
    assert manifest.runner_versions == {"test.runner_adapter": "v0"}
    assert {artifact.id for artifact in manifest.artifact_refs} == {
        "runner-adapter-boundary",
        "runner-adapter-snapshot",
        "runner-adapter-summary",
        "raw-measurements",
    }
    raw_artifact = require_artifact(manifest.artifact_refs, "raw-measurements")
    assert raw_artifact.kind == "measurement_dataset"
    assert_measurement_dataset_schema(
        raw_artifact.metadata,
        dataset_id="raw-measurements",
        dataset_role="raw",
        coordinates={"drive_frequency": "GHz"},
        observables={"signal": "ratio"},
    )
    assert snapshot.adapter_id == "test.runner_adapter"
    assert snapshot.measurement_count == 3
    assert snapshot.data_ref == "artifacts/raw-measurements.jsonl"

    persisted_manifest = read_model(run_dir / "manifest.json", RunManifest)
    persisted_config = read_model(
        run_dir / "config-profile.snapshot.json",
        ConfigProfileSnapshot,
    )
    assert (run_dir / "plan.snapshot.json").is_file()
    assert (run_dir / "events.jsonl").is_file()
    assert (run_dir / "artifacts" / "runner-adapter.summary.md").is_file()
    assert (run_dir / "artifacts" / "runner-adapter.snapshot.json").is_file()
    assert (run_dir / "artifacts" / "runner-adapter.boundary.json").is_file()
    assert (run_dir / "artifacts" / "raw-measurements.jsonl").is_file()
    assert persisted_manifest == manifest
    assert persisted_config == config
    boundary = read_model(
        run_dir / "artifacts" / "runner-adapter.boundary.json",
        RunnerAdapterBoundaryManifest,
    )
    assert boundary.schema_version == "scopecat.runner_adapter_boundary_manifest.v1"
    assert boundary.run_id == manifest.run_id
    assert boundary.status == "completed"
    assert boundary.runner_id == manifest.runner_id
    assert boundary.adapter_id == "test.runner_adapter"
    assert boundary.adapter_version == "v0"
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
    assert boundary.adapter_artifact_refs == []
    assert boundary.adapter_artifacts == []
    assert boundary.event_count == 5
    assert boundary.point_count == snapshot.point_count
    assert boundary.measurement_count == snapshot.measurement_count
    assert boundary.diagnostics == snapshot.diagnostics
    assert boundary.metadata == {"source": "fake_runner_adapter"}

    measurements = read_measurement_records(
        run_dir / "artifacts" / "raw-measurements.jsonl"
    )
    assert {item.schema_version for item in measurements} == {
        "scopecat.measurement_record.v0"
    }
    assert [item.point_index for item in measurements] == [0, 1, 2]
    assert [item.observables["signal"].value for item in measurements] == [
        0.25,
        0.375,
        0.5,
    ]

    events = read_jsonl_models(run_dir / "events.jsonl", RunEvent)
    assert [item.event_type for item in events] == [
        "runner_adapter_started",
        "runner_adapter_measurement_recorded",
        "runner_adapter_measurement_recorded",
        "runner_adapter_measurement_recorded",
        "runner_adapter_completed",
    ]


def test_execute_runner_adapter_supports_experiment_spec(
    tmp_path: Path,
) -> None:
    manifest, snapshot = execute_runner_adapter(
        config=load_config(),
        experiment=load_experiment(),
        adapter=KernelRunnerAdapter(),
        workspace=tmp_path,
    )

    run_dir = tmp_path / "runs" / manifest.run_id
    raw_artifact = require_artifact(manifest.artifact_refs, "raw-measurements")
    plan = read_model(run_dir / "plan.snapshot.json", PlanSnapshot)
    measurements = read_measurement_records(
        run_dir / "artifacts" / "raw-measurements.jsonl"
    )

    assert manifest.status == "completed"
    assert manifest.runner_id == "test.kernel_runner_adapter"
    assert snapshot.plan.schema_version == "scopecat.plan_snapshot.v1"
    assert snapshot.point_count == 3
    assert snapshot.measurement_count == 3
    assert plan == snapshot.plan
    assert plan.schema_version == "scopecat.plan_snapshot.v1"
    assert_measurement_dataset_schema(
        raw_artifact.metadata,
        dataset_id="raw-measurements",
        dataset_role="raw",
        coordinates={"drive_frequency": "GHz"},
        observables={"signal": "ratio"},
        dimension_label=None,
    )
    assert [item.point_index for item in measurements] == [0, 1, 2]
    assert [item.observables["signal"].value for item in measurements] == [
        0.25,
        0.375,
        0.5,
    ]


def test_runner_adapter_failure_registers_written_artifacts(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed):
        execute_runner_adapter(
            config=load_config(),
            experiment=load_experiment(),
            adapter=FailingAfterArtifactRunnerAdapter(),
            workspace=tmp_path,
        )

    manifests = open_run_store(tmp_path).list_runs()
    assert len(manifests) == 1
    manifest = manifests[0]
    run_dir = tmp_path / "runs" / manifest.run_id
    assert manifest.status == "failed"
    assert (run_dir / "artifacts" / "pre-failure-extra.txt").read_text() == (
        "written before failure\n"
    )
    artifact_ids = {artifact.id for artifact in manifest.artifact_refs}
    assert "pre-failure-extra" in artifact_ids


def test_runner_adapter_merges_adapter_owned_artifacts(tmp_path: Path) -> None:
    manifest, snapshot = execute_runner_adapter(
        config=load_config(),
        experiment=load_experiment(),
        adapter=ArtifactRunnerAdapter(),
        workspace=tmp_path,
    )

    run_dir = tmp_path / "runs" / manifest.run_id
    assert (run_dir / "artifacts" / "adapter-extra.txt").read_text() == (
        "adapter-owned artifact\n"
    )
    assert {artifact.id for artifact in manifest.artifact_refs} == {
        "adapter-extra",
        "runner-adapter-boundary",
        "runner-adapter-snapshot",
        "runner-adapter-summary",
        "raw-measurements",
    }
    boundary = read_model(
        run_dir / "artifacts" / "runner-adapter.boundary.json",
        RunnerAdapterBoundaryManifest,
    )
    assert boundary.adapter_artifact_refs == ["artifacts/adapter-extra.txt"]
    assert [
        (artifact.id, artifact.kind, artifact.path)
        for artifact in boundary.adapter_artifacts
    ] == [("adapter-extra", "adapter_artifact", "artifacts/adapter-extra.txt")]
    plan = read_model(run_dir / "plan.snapshot.json", PlanSnapshot)
    assert plan == snapshot.plan


def test_runner_adapter_uses_adapter_id_as_runner_id(tmp_path: Path) -> None:
    manifest, snapshot = execute_runner_adapter(
        config=load_simulated_config(),
        experiment=load_experiment(),
        adapter=FakeRunnerAdapter(),
        workspace=tmp_path,
    )

    run_dir = tmp_path / "runs" / manifest.run_id
    assert manifest.status == "completed"
    assert manifest.runner_id == "test.runner_adapter"
    assert manifest.dry_run is False
    assert {artifact.id for artifact in manifest.artifact_refs} == {
        "runner-adapter-boundary",
        "runner-adapter-snapshot",
        "runner-adapter-summary",
        "raw-measurements",
    }
    raw_artifact = require_artifact(manifest.artifact_refs, "raw-measurements")
    assert_measurement_dataset_schema(
        raw_artifact.metadata,
        dataset_id="raw-measurements",
        dataset_role="raw",
        coordinates={"drive_frequency": "GHz"},
        observables={"signal": "ratio"},
    )
    assert snapshot.runner_id == "test.runner_adapter"
    assert snapshot.dry_run is False
    assert snapshot.status == "completed"
    assert snapshot.data_ref == "artifacts/raw-measurements.jsonl"
    assert (run_dir / "artifacts" / "raw-measurements.jsonl").is_file()


def test_runner_adapter_plan_uses_raw_measurement_metadata(
    tmp_path: Path,
) -> None:
    manifest, _snapshot = execute_runner_adapter(
        config=load_config(),
        experiment=load_experiment(),
        adapter=FakeRunnerAdapter(),
        workspace=tmp_path,
    )

    raw_artifact = require_artifact(manifest.artifact_refs, "raw-measurements")
    assert_measurement_dataset_schema(
        raw_artifact.metadata,
        dataset_id="raw-measurements",
        dataset_role="raw",
        coordinates={"drive_frequency": "GHz"},
        observables={"signal": "ratio"},
    )

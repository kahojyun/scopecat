from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.errors import ValidationFailed
from scopecat.results import MeasurementDatasetSchema
from scopecat.runner import (
    RunnerAdapterBoundaryManifest,
    RunnerAdapterRunSnapshot,
    execute_runner_adapter,
)
from scopecat.runs import open_run_store
from tests.support.records import read_model, require_artifact
from tests.support.runner_adapter import (
    FailingRunnerAdapter,
    MismatchedObservableRunnerAdapter,
    UnsafeArtifactRunnerAdapter,
    load_config,
)
from tests.support.workflow_fixtures import load_experiment


def test_runner_adapter_failure_keeps_failed_run(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed) as error:
        execute_runner_adapter(
            config=load_config(),
            experiment=load_experiment(),
            adapter=FailingRunnerAdapter(),
            workspace=tmp_path,
        )

    assert error.value.diagnostics[-1].code == "runner_adapter_failed"
    manifests = open_run_store(tmp_path).list_runs()
    assert len(manifests) == 1
    assert manifests[0].status == "failed"
    run_dir = tmp_path / "runs" / manifests[0].run_id
    assert (run_dir / "artifacts" / "runner-adapter.snapshot.json").is_file()
    assert (run_dir / "artifacts" / "runner-adapter.boundary.json").is_file()
    assert (run_dir / "artifacts" / "raw-measurements.jsonl").read_text() == ""
    snapshot = read_model(
        run_dir / "artifacts" / "runner-adapter.snapshot.json",
        RunnerAdapterRunSnapshot,
    )
    boundary = read_model(
        run_dir / "artifacts" / "runner-adapter.boundary.json",
        RunnerAdapterBoundaryManifest,
    )
    assert snapshot.status == "failed"
    assert snapshot.plan.schema_version == "scopecat.plan_snapshot.v1"
    assert snapshot.diagnostics[-1].code == "runner_adapter_failed"
    assert boundary.status == "failed"
    assert boundary.plan_content_hash == snapshot.plan.content_hash
    assert boundary.point_count == snapshot.point_count
    assert boundary.measurement_count == snapshot.measurement_count
    assert boundary.diagnostics == snapshot.diagnostics
    assert boundary.diagnostics[-1].code == "runner_adapter_failed"


def test_runner_adapter_rejects_escaping_adapter_artifacts(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationFailed) as error:
        execute_runner_adapter(
            config=load_config(),
            experiment=load_experiment(),
            adapter=UnsafeArtifactRunnerAdapter(),
            workspace=tmp_path,
        )

    assert error.value.diagnostics[-1].code == (
        "runner_adapter_invalid_artifact_filename"
    )
    manifests = open_run_store(tmp_path).list_runs()
    assert len(manifests) == 1
    assert manifests[0].status == "failed"


def test_runner_adapter_schema_mismatch_keeps_failed_run(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed) as error:
        execute_runner_adapter(
            config=load_config(),
            experiment=load_experiment(),
            adapter=MismatchedObservableRunnerAdapter(),
            workspace=tmp_path,
        )

    codes = [diagnostic.code for diagnostic in error.value.diagnostics]
    assert "measurement_record_missing_observable" in codes
    assert "measurement_record_unexpected_observable" in codes
    manifests = open_run_store(tmp_path).list_runs()
    assert len(manifests) == 1
    assert manifests[0].status == "failed"
    raw_artifact = require_artifact(manifests[0].artifact_refs, "raw-measurements")
    raw_schema = MeasurementDatasetSchema.model_validate(
        raw_artifact.metadata["dataset_schema"]
    )
    assert raw_schema.primary_observables == ["signal"]

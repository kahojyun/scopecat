from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.kernel.errors import CheckFailed, DataIntegrityError, NotFound
from scopecat.records.measurement_recording import MeasurementDatasetAppend
from scopecat.runs.access import (
    dataset_storage_ref,
    list_payload_entries,
)
from scopecat.runs.service import (
    load_run_request,
    read_run_artifact_bytes,
    read_run_artifact_text,
    read_run_measurement_dataset,
)
from tests.testkit.runtime import (
    list_test_runs,
    sqlite_project_services,
    sqlite_run_repository,
)
from tests.testkit.signal_testkit import execute_signal_run
from tests.testkit.workflow_fixtures import (
    attach_binary_artifact,
    load_config,
    load_invocation,
)


def test_workflow_run_data_access_reads_runs_artifacts_and_datasets(
    tmp_path: Path,
) -> None:
    config = load_config()
    experiment = load_invocation()
    baseline = execute_signal_run(
        config=config,
        experiment=experiment,
        project_root=tmp_path,
    )
    candidate = execute_signal_run(
        config=config,
        experiment=experiment,
        project_root=tmp_path,
    )
    services = sqlite_project_services(tmp_path)
    runs = list_test_runs(services.runs)
    details = services.runs.read_manifest(candidate.run_id)
    run_config = services.runs.read_config_profile_snapshot(candidate.run_id)
    run_request = load_run_request(
        run_id=candidate.run_id, services=sqlite_project_services(tmp_path)
    )
    artifacts = details.artifacts
    payload_entries = list_payload_entries(details)
    measurement_datasets = list_payload_entries(details, kind="measurement_dataset")
    raw_dataset = read_run_measurement_dataset(
        run_id=candidate.run_id,
        services=sqlite_project_services(tmp_path),
    )
    assert [run.run_id for run in runs] == [
        baseline.run_id,
        candidate.run_id,
    ]
    assert details.run_id == candidate.run_id
    assert [dataset.id for dataset in details.datasets] == ["raw-measurements"]
    assert details.outcome is not None
    assert details.outcome.result == "succeeded"
    assert run_config.id == "simple-scan-profile"
    assert run_request.experiment_id == "test.workflow_scan"
    assert artifacts == ()
    assert [entry.id for entry in payload_entries] == ["raw-measurements"]
    assert [dataset.id for dataset in measurement_datasets] == ["raw-measurements"]
    assert raw_dataset.dataset_entry.id == "raw-measurements"
    assert raw_dataset.dataset.dataset_schema.dataset_id == "raw-measurements"
    assert len(raw_dataset.dataset.records) == 3


def test_workflow_run_data_access_rejects_invalid_reads(tmp_path: Path) -> None:
    run = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        project_root=tmp_path,
    )
    attach_binary_artifact(tmp_path, run.run_id)

    with pytest.raises(NotFound) as missing_run:
        sqlite_project_services(tmp_path).runs.read_manifest("run_missing")
    with pytest.raises(NotFound) as missing_artifact:
        read_run_artifact_text(
            run_id=run.run_id,
            selector="missing-artifact",
            services=sqlite_project_services(tmp_path),
        )
    with pytest.raises(CheckFailed) as path_escape:
        read_run_artifact_text(
            run_id=run.run_id,
            selector="../manifest.json",
            services=sqlite_project_services(tmp_path),
        )
    binary = read_run_artifact_bytes(
        run_id=run.run_id,
        selector="binary-artifact",
        services=sqlite_project_services(tmp_path),
    )

    assert missing_run.value.problems[0].code == "run.not_found"
    assert missing_artifact.value.problems[0].code == "run.artifact_not_found"
    assert path_escape.value.problems[0].code == ("run.artifact_selector_path_escape")
    assert binary.artifact.id == "binary-artifact"
    assert binary.content == b"\x00\x01"


def test_workflow_run_data_access_rejects_invalid_typed_storage_rows(
    tmp_path: Path,
) -> None:
    run = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        project_root=tmp_path,
    )
    raw_dataset = read_run_measurement_dataset(
        run_id=run.run_id,
        services=sqlite_project_services(tmp_path),
    )
    storage = sqlite_run_repository(tmp_path)

    invalid_measurement = raw_dataset.dataset.records[0].model_copy(
        update={"observables": {}}
    )
    raw_dataset_entry = next(
        dataset for dataset in run.datasets if dataset.id == "raw-measurements"
    )
    measurement_ref = (
        f"{dataset_storage_ref(raw_dataset_entry)}/chunks/00000000000000000000.json"
    )
    append = storage.read_model(
        run.run_id,
        measurement_ref,
        MeasurementDatasetAppend,
    )
    storage.write_model(
        run.run_id,
        measurement_ref,
        append.model_copy(update={"records": (invalid_measurement,)}),
    )
    with pytest.raises(DataIntegrityError) as invalid_scalar_row:
        read_run_measurement_dataset(
            run_id=run.run_id,
            services=sqlite_project_services(tmp_path),
        )

    assert invalid_scalar_row.value.problems[0].code == (
        "run.measurement_dataset.schema_invalid"
    )

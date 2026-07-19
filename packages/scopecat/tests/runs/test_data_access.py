from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.adapters.filesystem.run_repository import FilesystemRunRepository
from scopecat.composition.local import local_run_repository, local_workspace_services
from scopecat.kernel.errors import CheckFailed, DataIntegrityError, NotFound
from scopecat.records.config import config_content_hash
from scopecat.records.measurement_recording import MeasurementDatasetAppend
from scopecat.records.run import RunManifest
from scopecat.runs.access import (
    dataset_storage_ref,
)
from scopecat.runs.refs import CONFIG_PROFILE_SNAPSHOT_REF
from scopecat.runs.service import (
    list_run_artifacts,
    list_run_payload_entries,
    list_runs,
    load_run,
    load_run_config,
    load_run_request,
    read_run_artifact_bytes,
    read_run_artifact_text,
    read_run_data_array,
    read_run_data_table,
    read_run_measurement_dataset,
    start_run,
)
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import (
    attach_binary_artifact,
    attach_typed_data_artifacts,
    load_config,
    load_prepared_invocation,
)


def test_workflow_run_data_access_reads_runs_artifacts_and_datasets(
    tmp_path: Path,
) -> None:
    config = load_config()
    experiment = load_prepared_invocation()
    baseline = start_run(
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
        config=config,
        experiment=experiment,
        services=local_workspace_services(tmp_path),
    )
    candidate = start_run(
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
        config=config,
        experiment=experiment,
        services=local_workspace_services(tmp_path),
    )
    attach_typed_data_artifacts(tmp_path, candidate.run_id)

    runs = list_runs(services=local_workspace_services(tmp_path))
    details = load_run(
        run_id=candidate.run_id, services=local_workspace_services(tmp_path)
    )
    run_config = load_run_config(
        run_id=candidate.run_id, services=local_workspace_services(tmp_path)
    )
    run_request = load_run_request(
        run_id=candidate.run_id, services=local_workspace_services(tmp_path)
    )
    artifacts = list_run_artifacts(
        run_id=candidate.run_id,
        services=local_workspace_services(tmp_path),
    )
    payload_entries = list_run_payload_entries(
        run_id=candidate.run_id,
        services=local_workspace_services(tmp_path),
    )
    measurement_datasets = list_run_payload_entries(
        run_id=candidate.run_id,
        services=local_workspace_services(tmp_path),
        kind="measurement_dataset",
    )
    raw_dataset = read_run_measurement_dataset(
        run_id=candidate.run_id,
        services=local_workspace_services(tmp_path),
    )
    metrics = read_run_data_table(
        run_id=candidate.run_id,
        selector="metrics",
        services=local_workspace_services(tmp_path),
    )
    matrix = read_run_data_array(
        run_id=candidate.run_id,
        selector="readout-matrix",
        services=local_workspace_services(tmp_path),
    )

    assert [run.run_id for run in runs] == [
        baseline.run_id,
        candidate.run_id,
    ]
    assert details.run_id == candidate.run_id
    assert {dataset.id for dataset in details.datasets} >= {
        "raw-measurements",
        "metrics",
        "readout-matrix",
    }
    assert details.outcome is not None
    assert details.outcome.result == "succeeded"
    assert run_config.workspace_id == "example-workspace"
    assert run_request is not None
    assert run_request.id == "test.workflow_scan.request"
    assert artifacts == ()
    assert {entry.id for entry in payload_entries} >= {
        "raw-measurements",
        "metrics",
        "readout-matrix",
    }
    assert [dataset.id for dataset in measurement_datasets] == ["raw-measurements"]
    assert raw_dataset.dataset_entry.id == "raw-measurements"
    assert raw_dataset.dataset.dataset_schema.dataset_id == "raw-measurements"
    assert len(raw_dataset.dataset.records) == 3
    assert metrics.table.rows[0]["metric"] == "visibility"
    assert matrix.array.variables["readout_probability"] == [
        [0.99, 0.03],
        [0.01, 0.97],
    ]


def test_run_inputs_are_loaded_independently_for_capture_runs(tmp_path: Path) -> None:
    manifest = RunManifest(
        run_id="run_capture",
        lifecycle="accepted",
        config_content_hash=config_content_hash(load_config()),
    )
    config = load_config()
    storage = FilesystemRunRepository(tmp_path)
    storage.write_manifest(manifest)
    storage.write_model(
        manifest.run_id,
        CONFIG_PROFILE_SNAPSHOT_REF,
        config,
    )

    details = load_run(
        run_id=manifest.run_id, services=local_workspace_services(tmp_path)
    )
    loaded_config = load_run_config(
        run_id=manifest.run_id, services=local_workspace_services(tmp_path)
    )
    loaded_request = load_run_request(
        run_id=manifest.run_id, services=local_workspace_services(tmp_path)
    )
    assert details == manifest
    assert loaded_config == config
    assert loaded_request is None

    workspace = sc.open(tmp_path, config_profile=config)
    handle = workspace.get_run(manifest.run_id)
    assert handle.config == config
    assert handle.request is None


def test_workflow_run_data_access_rejects_invalid_reads(tmp_path: Path) -> None:
    run = start_run(
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
        config=load_config(),
        experiment=load_prepared_invocation(),
        services=local_workspace_services(tmp_path),
    )
    attach_binary_artifact(tmp_path, run.run_id)

    with pytest.raises(NotFound) as missing_run:
        load_run(run_id="run_missing", services=local_workspace_services(tmp_path))
    with pytest.raises(NotFound) as missing_artifact:
        read_run_artifact_text(
            run_id=run.run_id,
            selector="missing-artifact",
            services=local_workspace_services(tmp_path),
        )
    with pytest.raises(CheckFailed) as path_escape:
        read_run_artifact_text(
            run_id=run.run_id,
            selector="../manifest.json",
            services=local_workspace_services(tmp_path),
        )
    binary = read_run_artifact_bytes(
        run_id=run.run_id,
        selector="binary-artifact",
        services=local_workspace_services(tmp_path),
    )

    assert missing_run.value.problems[0].code == "run.not_found"
    assert missing_artifact.value.problems[0].code == "run.artifact_not_found"
    assert path_escape.value.problems[0].code == ("run.artifact_selector_path_escape")
    assert binary.artifact.id == "binary-artifact"
    assert binary.content == b"\x00\x01"


def test_workflow_run_data_access_rejects_invalid_typed_storage_rows(
    tmp_path: Path,
) -> None:
    run = start_run(
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
        config=load_config(),
        experiment=load_prepared_invocation(),
        services=local_workspace_services(tmp_path),
    )
    attach_typed_data_artifacts(tmp_path, run.run_id)

    raw_dataset = read_run_measurement_dataset(
        run_id=run.run_id,
        services=local_workspace_services(tmp_path),
    )
    storage = local_run_repository(tmp_path)

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
            services=local_workspace_services(tmp_path),
        )

    assert invalid_scalar_row.value.problems[0].code == (
        "run.measurement_dataset.schema_invalid"
    )

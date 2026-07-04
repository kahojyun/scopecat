from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.errors import ValidationFailed
from scopecat.experiments import PlanSnapshot
from scopecat.runs import dataset_storage_ref, open_run_store
from scopecat.workflows import (
    list_run_artifacts,
    list_run_payload_entries,
    list_runs,
    load_run,
    read_run_artifact_bytes,
    read_run_artifact_text,
    read_run_data_array,
    read_run_data_table,
    read_run_measurement_dataset,
    read_run_record_json,
)
from scopecat.workflows.runs import start_run
from tests.support.signal_instruments import TestSignalInstrumentProvider
from tests.support.workflow_fixtures import (
    attach_binary_artifact,
    attach_typed_data_artifacts,
    load_config,
    load_experiment,
)


def test_workflow_run_data_access_reads_runs_artifacts_and_datasets(
    tmp_path: Path,
) -> None:
    config = load_config()
    experiment = load_experiment()
    baseline = start_run(
        instrument_provider=TestSignalInstrumentProvider(),
        config=config,
        experiment=experiment,
        workspace=tmp_path,
    )
    candidate = start_run(
        instrument_provider=TestSignalInstrumentProvider(),
        config=config,
        experiment=experiment,
        workspace=tmp_path,
    )
    attach_typed_data_artifacts(tmp_path, candidate.run_id)

    runs = list_runs(workspace=tmp_path)
    details = load_run(run_id=candidate.run_id, workspace=tmp_path)
    artifacts = list_run_artifacts(
        run_id=candidate.run_id,
        workspace=tmp_path,
    )
    payload_entries = list_run_payload_entries(
        run_id=candidate.run_id,
        workspace=tmp_path,
    )
    measurement_datasets = list_run_payload_entries(
        run_id=candidate.run_id,
        workspace=tmp_path,
        kind="measurement_dataset",
    )
    snapshot = read_run_record_json(
        run_id=candidate.run_id,
        selector="execution-snapshot",
        workspace=tmp_path,
    )
    raw_dataset = read_run_measurement_dataset(
        run_id=candidate.run_id,
        workspace=tmp_path,
    )
    metrics = read_run_data_table(
        run_id=candidate.run_id,
        selector="metrics",
        workspace=tmp_path,
    )
    matrix = read_run_data_array(
        run_id=candidate.run_id,
        selector="readout-matrix",
        workspace=tmp_path,
    )

    assert [run.run_id for run in runs] == [
        baseline.run_id,
        candidate.run_id,
    ]
    assert details.manifest.run_id == candidate.run_id
    assert {dataset.id for dataset in details.manifest.datasets} >= {
        "raw-measurements",
        "metrics",
        "readout-matrix",
    }
    assert any(record.id == "execution-snapshot" for record in details.manifest.records)
    assert details.config.workspace_id == "example-workspace"
    assert isinstance(details.plan, PlanSnapshot)
    assert details.plan.expected_dataset_schema is not None
    assert artifacts == ()
    assert {entry.id for entry in payload_entries} >= {
        "raw-measurements",
        "metrics",
        "readout-matrix",
    }
    assert [dataset.id for dataset in measurement_datasets] == ["raw-measurements"]
    assert snapshot.content["status"] == "completed"
    assert snapshot.content["measurement_count"] == 3
    assert raw_dataset.dataset_entry.id == "raw-measurements"
    assert raw_dataset.dataset.dataset_schema.dataset_id == "raw-measurements"
    assert len(raw_dataset.dataset.records) == 3
    assert metrics.table.rows[0]["metric"] == "visibility"
    assert matrix.array.variables["readout_probability"] == [
        [0.99, 0.03],
        [0.01, 0.97],
    ]


def test_workflow_run_data_access_rejects_invalid_reads(tmp_path: Path) -> None:
    run = start_run(
        instrument_provider=TestSignalInstrumentProvider(),
        config=load_config(),
        experiment=load_experiment(),
        workspace=tmp_path,
    )
    attach_binary_artifact(tmp_path, run.run_id)

    with pytest.raises(ValidationFailed) as missing_run:
        load_run(run_id="run_missing", workspace=tmp_path)
    with pytest.raises(ValidationFailed) as missing_artifact:
        read_run_artifact_text(
            run_id=run.run_id,
            selector="missing-artifact",
            workspace=tmp_path,
        )
    with pytest.raises(ValidationFailed) as path_escape:
        read_run_artifact_text(
            run_id=run.run_id,
            selector="../manifest.json",
            workspace=tmp_path,
        )
    binary = read_run_artifact_bytes(
        run_id=run.run_id,
        selector="binary-artifact",
        workspace=tmp_path,
    )

    assert missing_run.value.diagnostics[0].code == "run_not_found"
    assert missing_artifact.value.diagnostics[0].code == "artifact_not_found"
    assert path_escape.value.diagnostics[0].code == "artifact_selector_path_escape"
    assert binary.artifact.id == "binary-artifact"
    assert binary.content == b"\x00\x01"


def test_workflow_run_data_access_rejects_invalid_typed_storage_rows(
    tmp_path: Path,
) -> None:
    run = start_run(
        instrument_provider=TestSignalInstrumentProvider(),
        config=load_config(),
        experiment=load_experiment(),
        workspace=tmp_path,
    )
    attach_typed_data_artifacts(tmp_path, run.run_id)

    raw_dataset = read_run_measurement_dataset(
        run_id=run.run_id,
        workspace=tmp_path,
    )
    storage = open_run_store(tmp_path)

    invalid_measurement = raw_dataset.dataset.records[0].model_copy(
        update={"observables": {}}
    )
    raw_dataset_entry = next(
        dataset for dataset in run.datasets if dataset.id == "raw-measurements"
    )
    measurement_path = storage.ref_path(
        run.run_id, dataset_storage_ref(raw_dataset_entry)
    )
    measurement_path.write_text(f"{invalid_measurement.model_dump_json()}\n")
    with pytest.raises(ValidationFailed) as invalid_scalar_row:
        read_run_measurement_dataset(
            run_id=run.run_id,
            workspace=tmp_path,
        )

    assert invalid_scalar_row.value.diagnostics[0].code == (
        "run_measurement_dataset_invalid_schema"
    )

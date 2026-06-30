from __future__ import annotations

from pathlib import Path

import pytest
from demo_lab_readout_iq_testkit import artifact_path, create_readout_iq_run
from demo_lab_records import (
    mutate_first_measurement_record,
    mutate_measurement_records,
    with_observable_copied_from,
    with_observable_unit,
    without_observable,
)
from scopecat.errors import ValidationFailed
from scopecat.runs import open_run_store

from quantum_lab_demo.readout.iq_quality_processing import (
    execute_readout_iq_quality_processing,
)


def test_readout_iq_quality_processing_requires_runner_data(tmp_path: Path) -> None:
    run_id = create_readout_iq_run(tmp_path)
    storage = open_run_store(tmp_path)
    manifest = storage.read_manifest(run_id)
    manifest.artifact_refs = [
        artifact
        for artifact in manifest.artifact_refs
        if artifact.id != "raw-measurements"
    ]
    storage.write_manifest(manifest)

    with pytest.raises(ValidationFailed) as error:
        execute_readout_iq_quality_processing(run_id=run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "readout_iq_quality_input_not_found"


def test_readout_iq_quality_processing_rejects_missing_observable(
    tmp_path: Path,
) -> None:
    run_id = create_readout_iq_run(tmp_path)
    runner_data = artifact_path(tmp_path, run_id, "raw-measurements")
    mutate_first_measurement_record(
        runner_data,
        lambda record: without_observable(record, "q1"),
    )

    with pytest.raises(ValidationFailed) as error:
        execute_readout_iq_quality_processing(run_id=run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "invalid_readout_iq_quality_input_schema"


def test_readout_iq_quality_processing_rejects_invalid_observable_unit(
    tmp_path: Path,
) -> None:
    run_id = create_readout_iq_run(tmp_path)
    runner_data = artifact_path(tmp_path, run_id, "raw-measurements")
    mutate_first_measurement_record(
        runner_data,
        lambda record: with_observable_unit(record, "i0", "dB"),
    )

    with pytest.raises(ValidationFailed) as error:
        execute_readout_iq_quality_processing(run_id=run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "invalid_readout_iq_quality_input_schema"


def test_readout_iq_quality_processing_rejects_unseparated_states(
    tmp_path: Path,
) -> None:
    run_id = create_readout_iq_run(tmp_path)
    runner_data = artifact_path(tmp_path, run_id, "raw-measurements")
    mutate_measurement_records(
        runner_data,
        lambda record: with_observable_copied_from(
            with_observable_copied_from(
                record,
                target_observable_id="i1",
                source_observable_id="i0",
            ),
            target_observable_id="q1",
            source_observable_id="q0",
        ),
    )

    with pytest.raises(ValidationFailed) as error:
        execute_readout_iq_quality_processing(run_id=run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "insufficient_readout_iq_state_separation"

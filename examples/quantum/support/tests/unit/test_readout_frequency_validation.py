from __future__ import annotations

from pathlib import Path

import pytest
from demo_lab_readout_frequency_testkit import (
    artifact_path,
    config_profile_snapshot,
    create_processed_readout_run,
    readout_frequency_adapter,
    readout_frequency_experiment,
)
from demo_lab_records import (
    mutate_first_measurement_record,
    mutate_measurement_records,
    without_observable,
)
from scopecat.errors import ValidationFailed
from scopecat.runner import execute_runner_adapter

from quantum_lab_demo.readout.frequency_evaluation import (
    execute_readout_frequency_evaluation,
)
from quantum_lab_demo.readout.frequency_processing import (
    PROCESSED_DATA_ARTIFACT_ID,
    execute_readout_frequency_processing,
)
from quantum_lab_demo.readout.frequency_reporting import (
    execute_readout_frequency_plot_report,
)
from quantum_lab_demo.readout.frequency_update import (
    execute_readout_frequency_parameter_update,
)


def test_readout_frequency_evaluation_requires_processed_dataset(
    tmp_path: Path,
) -> None:
    manifest, _snapshot = execute_runner_adapter(
        config=config_profile_snapshot(),
        experiment=readout_frequency_experiment(),
        adapter=readout_frequency_adapter(),
        workspace=tmp_path,
    )

    with pytest.raises(ValidationFailed) as error:
        execute_readout_frequency_evaluation(
            run_id=manifest.run_id,
            workspace=tmp_path,
        )

    assert error.value.diagnostics[0].code == "readout_evaluation_input_not_found"


def test_readout_frequency_plot_report_requires_processed_dataset(
    tmp_path: Path,
) -> None:
    manifest, _snapshot = execute_runner_adapter(
        config=config_profile_snapshot(),
        experiment=readout_frequency_experiment(),
        adapter=readout_frequency_adapter(),
        workspace=tmp_path,
    )

    with pytest.raises(ValidationFailed) as error:
        execute_readout_frequency_plot_report(
            run_id=manifest.run_id,
            workspace=tmp_path,
        )

    assert error.value.diagnostics[0].code == "readout_plot_report_input_not_found"


def test_readout_frequency_processing_rejects_missing_raw_observable(
    tmp_path: Path,
) -> None:
    manifest, _snapshot = execute_runner_adapter(
        config=config_profile_snapshot(),
        experiment=readout_frequency_experiment(),
        adapter=readout_frequency_adapter(),
        workspace=tmp_path,
    )
    runner_data = artifact_path(tmp_path, manifest.run_id, "raw-measurements")
    mutate_first_measurement_record(
        runner_data,
        lambda record: without_observable(record, "raw_q"),
    )

    with pytest.raises(ValidationFailed) as error:
        execute_readout_frequency_processing(
            run_id=manifest.run_id,
            workspace=tmp_path,
        )

    assert error.value.diagnostics[0].code == "invalid_readout_processing_input_schema"


def test_readout_frequency_plot_report_rejects_missing_observable(
    tmp_path: Path,
) -> None:
    run_id = create_processed_readout_run(tmp_path)
    processed_data = artifact_path(tmp_path, run_id, PROCESSED_DATA_ARTIFACT_ID)
    mutate_first_measurement_record(
        processed_data,
        lambda record: without_observable(record, "iq_phase"),
    )

    with pytest.raises(ValidationFailed) as error:
        execute_readout_frequency_plot_report(
            run_id=run_id,
            workspace=tmp_path,
        )

    assert error.value.diagnostics[0].code == "invalid_readout_plot_report_input_schema"


def test_readout_frequency_evaluation_rejects_missing_s21(
    tmp_path: Path,
) -> None:
    run_id = create_processed_readout_run(tmp_path)
    processed_data = artifact_path(tmp_path, run_id, PROCESSED_DATA_ARTIFACT_ID)
    mutate_measurement_records(
        processed_data,
        lambda record: without_observable(record, "s21_db"),
    )

    with pytest.raises(ValidationFailed) as error:
        execute_readout_frequency_evaluation(
            run_id=run_id,
            workspace=tmp_path,
        )

    assert error.value.diagnostics[0].code == "invalid_readout_evaluation_input_schema"


def test_readout_frequency_parameter_update_requires_evaluation(
    tmp_path: Path,
) -> None:
    run_id = create_processed_readout_run(tmp_path)

    with pytest.raises(ValidationFailed) as error:
        execute_readout_frequency_parameter_update(
            run_id=run_id,
            workspace=tmp_path,
            reviewer="operator",
            operator="operator",
        )

    assert error.value.diagnostics[0].code == "proposal_not_found"

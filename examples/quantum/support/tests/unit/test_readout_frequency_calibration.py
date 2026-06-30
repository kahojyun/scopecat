from __future__ import annotations

from pathlib import Path

from demo_lab_readout_frequency_testkit import (
    artifact_path,
    config_profile_snapshot,
    readout_frequency_adapter,
    readout_frequency_experiment,
)
from demo_lab_records import (
    assert_artifact_ref,
    assert_measurement_dataset_schema,
    contains_legacy_metadata,
    read_measurement_records,
    read_model,
)
from scopecat.models.artifact import ProcessingJob
from scopecat.models.parameter import Quantity
from scopecat.runner import execute_runner_adapter
from scopecat.runs import (
    open_run_store,
    read_artifact_bytes,
    read_artifact_text,
    read_model_artifact,
    require_artifact,
)
from scopecat.workflows import read_run_measurement_dataset

from quantum_lab_demo.readout.frequency_processing import (
    PROCESSED_DATA_ARTIFACT_ID,
    PROCESSED_DATA_REF,
    PROCESSED_RESULT_ARTIFACT_ID,
    PROCESSED_RESULT_REF,
    PROCESSED_SUMMARY_ARTIFACT_ID,
    PROCESSING_JOB_REF,
    READOUT_PROCESSING_STEP,
    ReadoutFrequencyProcessingResult,
    execute_readout_frequency_processing,
)
from quantum_lab_demo.readout.frequency_reporting import (
    READOUT_PLOT_REPORT_FIGURE_ARTIFACT_ID,
    READOUT_PLOT_REPORT_FIGURE_REF,
    READOUT_PLOT_REPORT_JOB_ARTIFACT_ID,
    READOUT_PLOT_REPORT_JOB_REF,
    READOUT_PLOT_REPORT_RESULT_ARTIFACT_ID,
    READOUT_PLOT_REPORT_RESULT_REF,
    READOUT_PLOT_REPORT_SUMMARY_ARTIFACT_ID,
    ReadoutFrequencyPlotReportResult,
    execute_readout_frequency_plot_report,
)


def test_readout_frequency_calibration_runner_adapter_flow(
    tmp_path: Path,
) -> None:
    config = config_profile_snapshot()
    manifest, snapshot = execute_runner_adapter(
        config=config,
        experiment=readout_frequency_experiment(),
        adapter=readout_frequency_adapter(),
        workspace=tmp_path,
    )

    run_id = manifest.run_id
    assert manifest.runner_versions == {
        "quantum_lab_demo.readout_frequency_calibration": "v0"
    }
    assert snapshot.adapter_id == ("quantum_lab_demo.readout_frequency_calibration")
    assert snapshot.measurement_count == 101
    raw_artifact = assert_artifact_ref(
        manifest.artifact_refs,
        "raw-measurements",
        kind="measurement_dataset",
    )
    assert_measurement_dataset_schema(
        raw_artifact.metadata,
        dataset_id="raw-measurements",
        dataset_role="raw",
        size=101,
        coordinates={"readout_frequency": "GHz"},
        observables={"raw_i": "ratio", "raw_q": "ratio"},
        dimension_label=None,
    )
    raw_dataset = read_run_measurement_dataset(run_id=run_id, workspace=tmp_path)
    assert raw_dataset.artifact.id == "raw-measurements"
    assert raw_dataset.dataset.dataset_schema.dataset_id == "raw-measurements"
    assert len(raw_dataset.dataset.records) == 101

    measurements = read_measurement_records(
        artifact_path(tmp_path, run_id, "raw-measurements")
    )
    assert [item.point_index for item in measurements] == list(range(101))
    metadata = measurements[0].metadata
    assert metadata["producer_kind"] == "adapter"
    assert metadata["producer_id"] == ("quantum_lab_demo.readout_frequency_calibration")
    assert metadata["adapter"] == ("quantum_lab_demo.readout_frequency_calibration")
    assert (
        metadata["anti_corruption"]
        == "offline replay of synthetic S21 scan semantics; no hardware connection"
    )
    assert (
        metadata["sample_reference"]
        == "sample-public://readout/frequency-calibration-s21"
    )
    assert metadata["source_function"] == "readout frequency response"
    assert not contains_legacy_metadata(metadata)
    assert set(measurements[0].observables) == {"raw_i", "raw_q"}
    for measurement in measurements:
        assert "s21_db" not in measurement.observables
        assert "iq_amplitude" not in measurement.observables
        assert "iq_phase" not in measurement.observables
        assert "readout_detuning" not in measurement.observables

    job, result = execute_readout_frequency_processing(
        run_id=run_id,
        workspace=tmp_path,
    )
    assert job.input_artifact_ids == ["raw-measurements"]
    assert job.input_record_refs == []
    assert job.output_artifact_ids == [
        PROCESSED_DATA_ARTIFACT_ID,
        PROCESSED_RESULT_ARTIFACT_ID,
        PROCESSED_SUMMARY_ARTIFACT_ID,
    ]
    assert result.measurement_count == 101
    assert result.output_ref == PROCESSED_DATA_REF

    storage = open_run_store(tmp_path)
    updated_manifest = storage.read_manifest(run_id)
    assert_artifact_ref(
        updated_manifest.artifact_refs,
        f"{READOUT_PROCESSING_STEP}-job",
        kind="processing_job",
        path=PROCESSING_JOB_REF,
    )
    persisted_processing_job = read_model(
        storage.ref_path(run_id, PROCESSING_JOB_REF),
        ProcessingJob,
    )
    assert persisted_processing_job == job
    persisted_processing_result = read_model_artifact(
        storage=storage,
        run_id=run_id,
        selector=PROCESSED_RESULT_ARTIFACT_ID,
        model_type=ReadoutFrequencyProcessingResult,
        expected_kind="readout_processing_result",
    )
    assert persisted_processing_result == result
    processing_result_artifact = require_artifact(
        manifest=updated_manifest,
        selector=PROCESSED_RESULT_ARTIFACT_ID,
        expected_kind="readout_processing_result",
    )
    assert processing_result_artifact.path == PROCESSED_RESULT_REF
    processed_artifact = assert_artifact_ref(
        updated_manifest.artifact_refs,
        PROCESSED_DATA_ARTIFACT_ID,
        kind="measurement_dataset",
        path=PROCESSED_DATA_REF,
    )
    assert_measurement_dataset_schema(
        processed_artifact.metadata,
        dataset_id=PROCESSED_DATA_ARTIFACT_ID,
        dataset_role="derived",
        size=101,
        coordinates={"readout_frequency": "GHz"},
        observables={
            "i": "ratio",
            "q": "ratio",
            "iq_amplitude": "ratio",
            "iq_phase": "rad",
            "readout_detuning": "MHz",
            "s21_db": "dB",
        },
        source_step="readout-frr-processing",
        source_artifact_ids=["raw-measurements"],
    )

    processed_measurements = read_measurement_records(
        artifact_path(tmp_path, run_id, PROCESSED_DATA_ARTIFACT_ID)
    )
    assert set(processed_measurements[0].observables) == {
        "i",
        "iq_amplitude",
        "iq_phase",
        "q",
        "readout_detuning",
        "s21_db",
    }
    assert processed_measurements[0].observables["s21_db"].unit == "dB"
    amplitudes = [
        item.observables["iq_amplitude"].value for item in processed_measurements
    ]
    assert amplitudes.index(min(amplitudes)) == 53

    plot_job, plot_result = execute_readout_frequency_plot_report(
        run_id=run_id,
        workspace=tmp_path,
    )
    assert plot_job.input_artifact_ids == [PROCESSED_DATA_ARTIFACT_ID]
    assert plot_job.input_record_refs == []
    assert plot_job.output_artifact_ids == [
        READOUT_PLOT_REPORT_RESULT_ARTIFACT_ID,
        READOUT_PLOT_REPORT_SUMMARY_ARTIFACT_ID,
        READOUT_PLOT_REPORT_FIGURE_ARTIFACT_ID,
    ]
    assert plot_result.measurement_count == 101
    assert plot_result.min_s21_point_index == 53
    assert plot_result.min_s21_readout_frequency == Quantity(
        value=5.953,
        unit="GHz",
    )
    assert plot_result.min_s21.unit == "dB"
    assert plot_result.figure_ref == READOUT_PLOT_REPORT_FIGURE_REF

    plotted_manifest = storage.read_manifest(run_id)
    assert_artifact_ref(
        plotted_manifest.artifact_refs,
        READOUT_PLOT_REPORT_JOB_ARTIFACT_ID,
        kind="processing_job",
        path=READOUT_PLOT_REPORT_JOB_REF,
    )
    persisted_plot_job = read_model(
        storage.ref_path(run_id, READOUT_PLOT_REPORT_JOB_REF),
        ProcessingJob,
    )
    assert persisted_plot_job == plot_job
    persisted_plot_result = read_model_artifact(
        storage=storage,
        run_id=run_id,
        selector=READOUT_PLOT_REPORT_RESULT_ARTIFACT_ID,
        model_type=ReadoutFrequencyPlotReportResult,
        expected_kind="readout_plot_report_result",
    )
    assert persisted_plot_result == plot_result
    assert_artifact_ref(
        plotted_manifest.artifact_refs,
        READOUT_PLOT_REPORT_RESULT_ARTIFACT_ID,
    )
    assert_artifact_ref(
        plotted_manifest.artifact_refs,
        READOUT_PLOT_REPORT_SUMMARY_ARTIFACT_ID,
    )
    assert_artifact_ref(
        plotted_manifest.artifact_refs,
        READOUT_PLOT_REPORT_FIGURE_ARTIFACT_ID,
    )
    plot_result_artifact = require_artifact(
        manifest=plotted_manifest,
        selector=READOUT_PLOT_REPORT_RESULT_ARTIFACT_ID,
        expected_kind="readout_plot_report_result",
    )
    assert plot_result_artifact.path == READOUT_PLOT_REPORT_RESULT_REF
    assert read_artifact_text(
        storage=storage,
        run_id=run_id,
        selector=READOUT_PLOT_REPORT_SUMMARY_ARTIFACT_ID,
    ).endswith("\n")
    figure_bytes = read_artifact_bytes(
        storage=storage,
        run_id=run_id,
        selector=READOUT_PLOT_REPORT_FIGURE_ARTIFACT_ID,
    )
    assert figure_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(figure_bytes) > 1024

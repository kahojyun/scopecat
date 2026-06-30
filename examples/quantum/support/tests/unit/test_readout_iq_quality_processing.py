from __future__ import annotations

from pathlib import Path

from demo_lab_readout_iq_testkit import artifact_path, create_readout_iq_run
from demo_lab_records import (
    assert_artifact_ref,
    assert_measurement_dataset_schema,
    read_measurement_records,
    read_model,
)
from demo_lab_test_paths import (
    READOUT_IQ_FIXTURE_DIR,
)
from scopecat.authoring import resolve_experiment
from scopecat.experiments import (
    ExperimentSpec,
    plan_experiment,
)
from scopecat.models.artifact import ProcessingJob
from scopecat.models.config import load_config_profile
from scopecat.runner import RunnerAdapterRunSnapshot
from scopecat.runs import (
    open_run_store,
    read_artifact_bytes,
    read_artifact_text,
    read_model_artifact,
    require_artifact,
)
from scopecat.workflows import AnalysisStepCatalogContext

from quantum_lab_demo.readout import (
    READOUT_IQ_QUALITY_ANALYSIS_STEP,
    ReadoutIQQualityAnalysisStep,
    iq_quality,
)
from quantum_lab_demo.readout.analysis_catalog import ReadoutAnalysisCatalog
from quantum_lab_demo.readout.iq_quality_processing import (
    READOUT_IQ_FIGURE_ARTIFACT_ID,
    READOUT_IQ_FIGURE_REF,
    READOUT_IQ_JOB_ARTIFACT_ID,
    READOUT_IQ_JOB_REF,
    READOUT_IQ_MATRIX_ARTIFACT_ID,
    READOUT_IQ_METRICS_ARTIFACT_ID,
    READOUT_IQ_PROCESSED_ARTIFACT_ID,
    READOUT_IQ_PROCESSED_REF,
    READOUT_IQ_RESULT_ARTIFACT_ID,
    READOUT_IQ_RESULT_REF,
    READOUT_IQ_SUMMARY_ARTIFACT_ID,
    READOUT_IQ_SUMMARY_REF,
    ReadoutIQQualityProcessingResult,
    execute_readout_iq_quality_processing,
)


def test_readout_iq_quality_catalog_resolves_expected_analysis_step() -> None:
    catalog = ReadoutAnalysisCatalog()
    description = catalog.describe()

    analysis = catalog.analysis_step(
        AnalysisStepCatalogContext(step_id=READOUT_IQ_QUALITY_ANALYSIS_STEP)
    )
    unsupported = catalog.analysis_step(
        AnalysisStepCatalogContext(step_id="missing-analysis")
    )

    assert description.catalog_id == "quantum_lab_demo.readout_analysis"
    assert [step.step_id for step in description.steps] == [
        "readout.frequency.analysis",
        "readout.iq_quality.analysis",
    ]
    assert description.steps[1].output_artifact_kinds == ("analysis",)
    assert isinstance(analysis.step, ReadoutIQQualityAnalysisStep)
    assert unsupported.diagnostics[0].code == "readout_analysis_step_unsupported"


def test_readout_iq_quality_template_builds_shot_schema() -> None:
    config = load_config_profile(READOUT_IQ_FIXTURE_DIR / "config-profile.json")
    resolved = resolve_experiment(
        iq_quality(qubit="q0"),
        workspace=READOUT_IQ_FIXTURE_DIR,
        config_profile=config,
    )
    assert config.parameter_build is not None
    resolved_experiment = resolved.experiment
    assert isinstance(resolved_experiment, ExperimentSpec)
    plan = plan_experiment(resolved_experiment, config.parameter_build)
    schema = plan.expected_dataset_schema

    assert resolved.template_id == "quantum_lab_demo.readout.iq_quality"
    assert resolved_experiment.points.evaluate(config.parameter_build) == [{}]
    assert schema is not None
    assert schema.dimensions[0].id == "shot"
    assert schema.dimensions[0].size == 240
    assert schema.primary_coordinates == ["shot_index"]
    assert schema.primary_observables == ["i0", "q0", "i1", "q1"]


def test_readout_iq_quality_processing_flow(tmp_path: Path) -> None:
    run_id = create_readout_iq_run(tmp_path)
    storage = open_run_store(tmp_path)
    manifest = storage.read_manifest(run_id)
    snapshot = read_model_artifact(
        storage=storage,
        run_id=run_id,
        selector="runner-adapter-snapshot",
        model_type=RunnerAdapterRunSnapshot,
        expected_kind="runner_adapter_run_snapshot",
    )

    assert manifest.runner_versions == {"quantum_lab_demo.readout_iq_scatter": "v0"}
    assert snapshot.adapter_id == "quantum_lab_demo.readout_iq_scatter"
    assert snapshot.measurement_count == 240
    raw_artifact = assert_artifact_ref(
        manifest.artifact_refs,
        "raw-measurements",
        kind="measurement_dataset",
    )
    assert_measurement_dataset_schema(
        raw_artifact.metadata,
        dataset_id="raw-measurements",
        dataset_role="raw",
        size=240,
        coordinates={"shot_index": "count"},
        observables={
            "i0": "ratio",
            "q0": "ratio",
            "i1": "ratio",
            "q1": "ratio",
        },
        dimension_label=None,
    )

    raw_measurements = read_measurement_records(
        artifact_path(tmp_path, run_id, "raw-measurements")
    )
    assert len(raw_measurements) == 240
    assert set(raw_measurements[0].observables) == {"i0", "q0", "i1", "q1"}
    metadata = raw_measurements[0].metadata
    assert metadata["producer_kind"] == "adapter"
    assert metadata["producer_id"] == "quantum_lab_demo.readout_iq_scatter"
    assert metadata["adapter"] == "quantum_lab_demo.readout_iq_scatter"
    assert (
        metadata["anti_corruption"]
        == "offline replay of synthetic IQ scatter semantics; no hardware connection"
    )
    assert metadata["sample_reference"] == "sample-public://readout/iq-quality"
    assert metadata["source_function"] == "readout IQ scatter"
    assert metadata["state0_label"] == "|0>"
    assert metadata["state1_label"] == "|1>"

    job, result = execute_readout_iq_quality_processing(
        run_id=run_id,
        workspace=tmp_path,
    )

    assert job.input_artifact_ids == ["raw-measurements"]
    assert job.input_record_refs == []
    assert job.output_artifact_ids == [
        READOUT_IQ_PROCESSED_ARTIFACT_ID,
        READOUT_IQ_RESULT_ARTIFACT_ID,
        READOUT_IQ_METRICS_ARTIFACT_ID,
        READOUT_IQ_MATRIX_ARTIFACT_ID,
        READOUT_IQ_SUMMARY_ARTIFACT_ID,
        READOUT_IQ_FIGURE_ARTIFACT_ID,
    ]
    assert result.measurement_count == 240
    assert result.visibility.value > 0.9
    assert result.p00.value > 0.9
    assert result.p11.value > 0.9
    assert result.snr.value > 10
    assert result.threshold.unit == "ratio"
    assert result.rotation_angle.unit == "rad"
    assert len(result.readout_matrix) == 2
    assert len(result.readout_matrix[0]) == 2

    updated_manifest = storage.read_manifest(run_id)
    assert_artifact_ref(
        updated_manifest.artifact_refs,
        READOUT_IQ_JOB_ARTIFACT_ID,
        kind="processing_job",
        path=READOUT_IQ_JOB_REF,
    )
    persisted_job = read_model(
        storage.ref_path(run_id, READOUT_IQ_JOB_REF),
        ProcessingJob,
    )
    assert persisted_job == job
    persisted_result = read_model_artifact(
        storage=storage,
        run_id=run_id,
        selector=READOUT_IQ_RESULT_ARTIFACT_ID,
        model_type=ReadoutIQQualityProcessingResult,
        expected_kind="readout_iq_quality_processing_result",
    )
    assert persisted_result == result
    artifact_ids = {artifact.id for artifact in updated_manifest.artifact_refs}
    assert READOUT_IQ_PROCESSED_ARTIFACT_ID in artifact_ids
    assert READOUT_IQ_RESULT_ARTIFACT_ID in artifact_ids
    assert READOUT_IQ_METRICS_ARTIFACT_ID in artifact_ids
    assert READOUT_IQ_MATRIX_ARTIFACT_ID in artifact_ids
    assert READOUT_IQ_SUMMARY_ARTIFACT_ID in artifact_ids
    assert READOUT_IQ_FIGURE_ARTIFACT_ID in artifact_ids
    result_artifact = require_artifact(
        manifest=updated_manifest,
        selector=READOUT_IQ_RESULT_ARTIFACT_ID,
        expected_kind="readout_iq_quality_processing_result",
    )
    assert result_artifact.path == READOUT_IQ_RESULT_REF
    processed_artifact = assert_artifact_ref(
        updated_manifest.artifact_refs,
        READOUT_IQ_PROCESSED_ARTIFACT_ID,
        kind="measurement_dataset",
        path=READOUT_IQ_PROCESSED_REF,
    )
    assert_measurement_dataset_schema(
        processed_artifact.metadata,
        dataset_id=READOUT_IQ_PROCESSED_ARTIFACT_ID,
        dataset_role="derived",
        size=240,
        coordinates={"shot_index": "count"},
        observables={
            "state0_rotated_i": "ratio",
            "state0_rotated_q": "ratio",
            "state1_rotated_i": "ratio",
            "state1_rotated_q": "ratio",
            "state0_assignment": "count",
            "state1_assignment": "count",
        },
        source_step="readout-iq-quality-processing",
        source_artifact_ids=["raw-measurements"],
    )

    processed_measurements = read_measurement_records(
        artifact_path(tmp_path, run_id, READOUT_IQ_PROCESSED_ARTIFACT_ID)
    )
    assert len(processed_measurements) == 240
    assert set(processed_measurements[0].observables) == {
        "state0_assignment",
        "state0_rotated_i",
        "state0_rotated_q",
        "state1_assignment",
        "state1_rotated_i",
        "state1_rotated_q",
    }
    summary_artifact = require_artifact(
        manifest=updated_manifest,
        selector=READOUT_IQ_SUMMARY_ARTIFACT_ID,
        expected_kind="summary",
    )
    assert summary_artifact.path == READOUT_IQ_SUMMARY_REF
    assert read_artifact_text(
        storage=storage,
        run_id=run_id,
        selector=READOUT_IQ_SUMMARY_ARTIFACT_ID,
    ).endswith("\n")
    figure_artifact = require_artifact(
        manifest=updated_manifest,
        selector=READOUT_IQ_FIGURE_ARTIFACT_ID,
        expected_kind="plot",
    )
    assert figure_artifact.path == READOUT_IQ_FIGURE_REF
    figure_bytes = read_artifact_bytes(
        storage=storage,
        run_id=run_id,
        selector=READOUT_IQ_FIGURE_ARTIFACT_ID,
    )
    assert figure_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(figure_bytes) > 1024

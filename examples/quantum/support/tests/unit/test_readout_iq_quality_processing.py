from __future__ import annotations

from pathlib import Path

from demo_lab_readout_iq_testkit import create_readout_iq_run
from demo_lab_records import (
    assert_artifact_ref,
)
from demo_lab_test_paths import (
    READOUT_IQ_FIXTURE_DIR,
)
from scopecat.authoring import resolve_experiment
from scopecat.experiments import (
    ExperimentSpec,
    plan_experiment,
)
from scopecat.models.config import load_config_profile
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

    assert_artifact_ref(
        manifest.artifact_refs,
        "raw-measurements",
        kind="measurement_dataset",
    )

    job, result = execute_readout_iq_quality_processing(
        run_id=run_id,
        workspace=tmp_path,
    )

    assert job.input_artifact_ids == ["raw-measurements"]
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
    persisted_result = read_model_artifact(
        storage=storage,
        run_id=run_id,
        selector=READOUT_IQ_RESULT_ARTIFACT_ID,
        model_type=ReadoutIQQualityProcessingResult,
        expected_kind="readout_iq_quality_processing_result",
    )
    assert persisted_result == result
    artifact_ids = {artifact.id for artifact in updated_manifest.artifact_refs}
    assert {
        READOUT_IQ_PROCESSED_ARTIFACT_ID,
        READOUT_IQ_RESULT_ARTIFACT_ID,
        READOUT_IQ_METRICS_ARTIFACT_ID,
        READOUT_IQ_MATRIX_ARTIFACT_ID,
        READOUT_IQ_SUMMARY_ARTIFACT_ID,
        READOUT_IQ_FIGURE_ARTIFACT_ID,
    } <= artifact_ids
    result_artifact = require_artifact(
        manifest=updated_manifest,
        selector=READOUT_IQ_RESULT_ARTIFACT_ID,
        expected_kind="readout_iq_quality_processing_result",
    )
    assert result_artifact.path == READOUT_IQ_RESULT_REF
    assert_artifact_ref(
        updated_manifest.artifact_refs,
        READOUT_IQ_PROCESSED_ARTIFACT_ID,
        kind="measurement_dataset",
        path=READOUT_IQ_PROCESSED_REF,
    )
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

from __future__ import annotations

from pathlib import Path

from demo_lab_readout_frequency_testkit import (
    artifact_path,
    create_processed_readout_run,
)
from demo_lab_records import assert_artifact_ref, read_model
from demo_lab_test_paths import PACKAGE_ROOT
from scopecat.evaluation import EvaluationJob
from scopecat.models.parameter import ParameterChangeSet, Quantity
from scopecat.runs import open_run_store, read_model_artifact, require_artifact

from quantum_lab_demo.readout.frequency_evaluation import (
    READOUT_EVALUATION_JOB_ARTIFACT_ID,
    READOUT_EVALUATION_JOB_REF,
    READOUT_EVALUATION_RESULT_ARTIFACT_ID,
    READOUT_EVALUATION_RESULT_REF,
    READOUT_EVALUATION_SUMMARY_ARTIFACT_ID,
    READOUT_RESONATOR_PROPOSAL_ARTIFACT_ID,
    READOUT_RESONATOR_PROPOSAL_REF,
    ReadoutFrequencyEvaluationResult,
    execute_readout_frequency_evaluation,
)


def test_readout_frequency_evaluation_persists_result_proposal_and_manifest(
    tmp_path: Path,
) -> None:
    run_id = create_processed_readout_run(tmp_path)
    storage = open_run_store(tmp_path)

    evaluation_job, evaluation_result, proposal = execute_readout_frequency_evaluation(
        run_id=run_id,
        workspace=tmp_path,
    )

    assert evaluation_job.input_artifact_ids == ["readout-frr-processed"]
    assert evaluation_job.input_record_refs == ["config.snapshot.json"]
    assert evaluation_job.output_artifact_ids == [
        READOUT_EVALUATION_RESULT_ARTIFACT_ID,
        READOUT_EVALUATION_SUMMARY_ARTIFACT_ID,
        READOUT_RESONATOR_PROPOSAL_ARTIFACT_ID,
    ]
    assert evaluation_result.best_point_index == 53
    assert evaluation_result.minimum_s21.unit == "dB"
    assert evaluation_result.old_value.value == 5.95
    assert evaluation_result.old_value.unit == "GHz"
    assert evaluation_result.proposed_value.value == 5.953
    assert evaluation_result.proposed_value.unit == "GHz"
    assert proposal.id == "readout-frr-min-s21"
    patch = proposal.patches[0]
    assert patch.parameter_id == "readout_frequency"
    assert isinstance(patch.value, Quantity)
    assert patch.value.value == 5.953
    assert patch.value.unit == "GHz"
    assert proposal.reason == "Minimum S21 observed at point 53."
    assert proposal.confidence == 1.0
    assert proposal.state == "proposed"

    evaluated_manifest = storage.read_manifest(run_id)
    assert_artifact_ref(
        evaluated_manifest.artifact_refs,
        READOUT_RESONATOR_PROPOSAL_ARTIFACT_ID,
        kind="parameter_change_set",
        path=READOUT_RESONATOR_PROPOSAL_REF,
    )
    persisted_evaluation_job = read_model(
        storage.ref_path(run_id, READOUT_EVALUATION_JOB_REF),
        EvaluationJob,
    )
    assert persisted_evaluation_job == evaluation_job
    persisted_evaluation_result = read_model_artifact(
        storage=storage,
        run_id=run_id,
        selector=READOUT_EVALUATION_RESULT_ARTIFACT_ID,
        model_type=ReadoutFrequencyEvaluationResult,
        expected_kind="readout_frequency_evaluation_result",
    )
    assert persisted_evaluation_result == evaluation_result
    persisted_proposal = read_model_artifact(
        storage=storage,
        run_id=run_id,
        selector=READOUT_RESONATOR_PROPOSAL_ARTIFACT_ID,
        model_type=ParameterChangeSet,
        expected_kind="parameter_change_set",
    )
    assert persisted_proposal == proposal
    assert_artifact_ref(
        evaluated_manifest.artifact_refs,
        READOUT_EVALUATION_JOB_ARTIFACT_ID,
        path=READOUT_EVALUATION_JOB_REF,
    )
    assert_artifact_ref(
        evaluated_manifest.artifact_refs,
        READOUT_EVALUATION_RESULT_ARTIFACT_ID,
    )
    assert_artifact_ref(
        evaluated_manifest.artifact_refs,
        READOUT_EVALUATION_SUMMARY_ARTIFACT_ID,
    )
    assert_artifact_ref(
        evaluated_manifest.artifact_refs,
        READOUT_RESONATOR_PROPOSAL_ARTIFACT_ID,
    )
    evaluation_result_artifact = require_artifact(
        manifest=evaluated_manifest,
        selector=READOUT_EVALUATION_RESULT_ARTIFACT_ID,
        expected_kind="readout_frequency_evaluation_result",
    )
    assert evaluation_result_artifact.path == READOUT_EVALUATION_RESULT_REF
    proposal_artifact = require_artifact(
        manifest=evaluated_manifest,
        selector=READOUT_RESONATOR_PROPOSAL_ARTIFACT_ID,
        expected_kind="parameter_change_set",
    )
    assert proposal_artifact.path == READOUT_RESONATOR_PROPOSAL_REF
    assert artifact_path(tmp_path, run_id, READOUT_RESONATOR_PROPOSAL_REF).is_file()


def test_readout_frequency_evaluation_uses_sdk_persistence_boundary() -> None:
    source = (
        PACKAGE_ROOT
        / "src"
        / "quantum_lab_demo"
        / "readout"
        / "frequency_evaluation.py"
    ).read_text()

    assert "storage.write_model" not in source
    assert "storage.write_text" not in source
    assert "storage.write_manifest" not in source
    assert "append_unique" not in source
    assert "upsert_artifacts" not in source
    assert "manifest.artifact_refs" not in source

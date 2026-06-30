from __future__ import annotations

import json
from pathlib import Path

import pytest

from scopecat.errors import ValidationFailed
from scopecat.evaluation import EvaluationJob
from scopecat.experiments import PlanSnapshot
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import (
    ParameterChangeSet,
    Quantity,
)
from scopecat.runs import open_run_store
from tests.support.evaluation import (
    assert_failed_evaluation_job,
    simulate,
)
from tests.support.records import (
    assert_artifact_ref,
    read_measurement_records,
    read_model,
)
from tests.support.signal_testkit import (
    BEST_SIGNAL_EVALUATION_JOB_REF,
    BEST_SIGNAL_EVALUATION_RESULT_REF,
    BEST_SIGNAL_EVALUATION_SUMMARY_REF,
    BEST_SIGNAL_PROPOSAL_REF,
    BestSignalEvaluationResult,
    execute_best_signal_evaluation,
)


def test_best_signal_evaluation_writes_proposal_and_manifest(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)

    job, result, proposal = execute_best_signal_evaluation(
        run_id=run_id,
        workspace=tmp_path,
    )

    run_dir = tmp_path / "runs" / run_id
    assert (run_dir / "evaluation" / "best-signal-proposal.job.json").is_file()
    assert (run_dir / "artifacts" / "best-signal-evaluation.json").is_file()
    assert (run_dir / "artifacts" / "best-signal-evaluation.md").is_file()
    assert (run_dir / "proposals" / "best-signal-proposal.json").is_file()

    assert job.status == "completed"
    assert result.parameter_id == "drive_frequency"
    assert result.best_point_index == 1
    assert result.best_signal.value == 1.0
    patch = proposal.patches[0]
    assert patch.kind == "set_scalar"
    assert patch.parameter_id == "drive_frequency"
    assert isinstance(patch.expected_value, Quantity)
    assert patch.expected_value.value == 5.0
    assert patch.expected_value.unit == "GHz"
    assert isinstance(patch.value, Quantity)
    assert patch.value.value == 5.0
    assert patch.value.unit == "GHz"
    assert proposal.reason == "Best signal observed at point 1."
    assert proposal.confidence == 1.0
    assert proposal.state == "proposed"
    persisted_job = read_model(run_dir / BEST_SIGNAL_EVALUATION_JOB_REF, EvaluationJob)
    persisted_result = read_model(
        run_dir / BEST_SIGNAL_EVALUATION_RESULT_REF,
        BestSignalEvaluationResult,
    )
    persisted_proposal = read_model(
        run_dir / BEST_SIGNAL_PROPOSAL_REF,
        ParameterChangeSet,
    )
    assert persisted_job == job
    assert persisted_result == result
    assert persisted_proposal == proposal

    manifest = open_run_store(tmp_path).read_manifest(run_id)
    assert manifest.status == "completed"
    assert_artifact_ref(
        manifest.artifact_refs,
        "best-signal-evaluation-result",
        kind="test_best_signal_evaluation_result",
        path=BEST_SIGNAL_EVALUATION_RESULT_REF,
    )
    assert_artifact_ref(
        manifest.artifact_refs,
        "best-signal-evaluation-summary",
        kind="summary",
        path=BEST_SIGNAL_EVALUATION_SUMMARY_REF,
    )
    assert_artifact_ref(
        manifest.artifact_refs,
        "best-signal-evaluation-job",
        kind="evaluation_job",
        path=BEST_SIGNAL_EVALUATION_JOB_REF,
    )
    assert_artifact_ref(
        manifest.artifact_refs,
        "best-signal-proposal",
        kind="parameter_change_set",
        path=BEST_SIGNAL_PROPOSAL_REF,
    )


def test_best_signal_evaluation_missing_data(tmp_path: Path) -> None:
    run_id = simulate(tmp_path)
    (tmp_path / "runs" / run_id / "artifacts" / "raw-measurements.jsonl").unlink()

    with pytest.raises(ValidationFailed) as error:
        execute_best_signal_evaluation(run_id=run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "missing_evaluation_input"
    job, _manifest = assert_failed_evaluation_job(
        tmp_path,
        run_id,
        step_id="best-signal-proposal",
        diagnostic_code="missing_evaluation_input",
    )
    assert job.input_artifact_ids == ["raw-measurements"]
    assert job.input_record_refs == []
    assert job.output_artifact_ids == []


def test_best_signal_evaluation_missing_signal(tmp_path: Path) -> None:
    run_id = simulate(tmp_path)
    data_path = tmp_path / "runs" / run_id / "artifacts" / "raw-measurements.jsonl"
    lines = []
    for record in read_measurement_records(data_path):
        item = record.model_dump(mode="json")
        item["observables"] = {}
        lines.append(json.dumps(item, separators=(",", ":")))
    data_path.write_text("\n".join(lines) + "\n")

    with pytest.raises(ValidationFailed) as error:
        execute_best_signal_evaluation(run_id=run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "invalid_evaluation_input_schema"
    assert_failed_evaluation_job(
        tmp_path,
        run_id,
        step_id="best-signal-proposal",
        diagnostic_code="invalid_evaluation_input_schema",
    )


def test_best_signal_evaluation_missing_sweep_parameter(tmp_path: Path) -> None:
    run_id = simulate(tmp_path)
    plan_path = tmp_path / "runs" / run_id / "plan.snapshot.json"
    persisted_plan = read_model(plan_path, PlanSnapshot)
    plan = persisted_plan.model_dump(mode="json")
    plan["point_coordinate_ids"] = []
    plan["expected_dataset_schema"]["primary_coordinates"] = []
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")

    with pytest.raises(ValidationFailed) as error:
        execute_best_signal_evaluation(run_id=run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "missing_sweep_coordinate"
    assert_failed_evaluation_job(
        tmp_path,
        run_id,
        step_id="best-signal-proposal",
        diagnostic_code="missing_sweep_coordinate",
    )


def test_best_signal_evaluation_missing_parameter_value(tmp_path: Path) -> None:
    run_id = simulate(tmp_path)
    config_path = tmp_path / "runs" / run_id / "config-profile.snapshot.json"
    persisted_config = read_model(config_path, ConfigProfileSnapshot)
    config = persisted_config.model_dump(mode="json")
    config["parameter_state"]["scalar_values"]["values"] = []
    config_path.write_text(json.dumps(config, indent=2) + "\n")

    with pytest.raises(ValidationFailed) as error:
        execute_best_signal_evaluation(run_id=run_id, workspace=tmp_path)

    assert error.value.diagnostics[0].code == "missing_parameter_value"
    assert_failed_evaluation_job(
        tmp_path,
        run_id,
        step_id="best-signal-proposal",
        diagnostic_code="missing_parameter_value",
    )

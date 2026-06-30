from __future__ import annotations

from pathlib import Path

from scopecat.evaluation import (
    EvaluationJob,
    execute_evaluation_step,
)
from scopecat.models.parameter import ParameterChangeSet
from scopecat.runs import open_run_store
from tests.support.evaluation import simulate
from tests.support.evaluation_sdk import FakeEvaluationResult, FakeEvaluationStep
from tests.support.records import assert_artifact_ref, read_model


def test_evaluation_sdk_persists_job_outputs_proposal_and_manifest(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)

    job, result, proposals = execute_evaluation_step(
        run_id=run_id,
        workspace=tmp_path,
        step=FakeEvaluationStep(),
    )

    run_dir = tmp_path / "runs" / run_id
    assert result.measurement_count == 3
    assert len(proposals) == 1
    assert proposals[0].id == "fake-evaluation"
    assert job.input_artifact_ids == ["raw-measurements"]
    assert job.input_record_refs == [
        "config-profile.snapshot.json",
        "plan.snapshot.json",
    ]
    assert job.output_artifact_ids == [
        "fake-evaluation-result",
        "fake-evaluation-summary",
        "fake-evaluation-proposal",
    ]
    assert [
        (artifact.id, artifact.kind, artifact.path) for artifact in job.output_artifacts
    ] == [
        (
            "fake-evaluation-result",
            "fake_evaluation_result",
            "artifacts/fake-evaluation.json",
        ),
        ("fake-evaluation-summary", "summary", "artifacts/fake-evaluation.md"),
        (
            "fake-evaluation-proposal",
            "parameter_change_set",
            "proposals/fake-evaluation-proposal.json",
        ),
    ]
    assert (run_dir / "artifacts" / "fake-evaluation.md").is_file()
    persisted_job = read_model(
        run_dir / "evaluation" / "fake-evaluation.job.json",
        EvaluationJob,
    )
    persisted_result = read_model(
        run_dir / "artifacts" / "fake-evaluation.json",
        FakeEvaluationResult,
    )
    persisted_proposal = read_model(
        run_dir / "proposals" / "fake-evaluation-proposal.json",
        ParameterChangeSet,
    )
    assert persisted_job == job
    assert persisted_result == result
    assert persisted_proposal == proposals[0]

    manifest = open_run_store(tmp_path).read_manifest(run_id)
    assert_artifact_ref(
        manifest.artifact_refs,
        "fake-evaluation-proposal",
        kind="parameter_change_set",
        path="proposals/fake-evaluation-proposal.json",
    )
    assert {artifact.id for artifact in manifest.artifact_refs} >= {
        "fake-evaluation-result",
        "fake-evaluation-summary",
        "fake-evaluation-job",
        "fake-evaluation-proposal",
    }

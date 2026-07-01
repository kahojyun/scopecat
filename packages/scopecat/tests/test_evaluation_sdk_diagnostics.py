from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.errors import ValidationFailed
from scopecat.evaluation import execute_evaluation_step
from tests.support.evaluation import assert_failed_evaluation_job, simulate
from tests.support.evaluation_sdk import (
    InvalidArtifactFilenameEvaluationStep,
    ProposalThenFailEvaluationStep,
    UnexpectedEvaluationFailureStep,
)


def test_evaluation_sdk_rejects_invalid_artifact_filename(tmp_path: Path) -> None:
    run_id = simulate(tmp_path)

    with pytest.raises(ValidationFailed) as error:
        execute_evaluation_step(
            run_id=run_id,
            workspace=tmp_path,
            step=InvalidArtifactFilenameEvaluationStep(),
        )

    assert error.value.diagnostics[0].code == "evaluation_invalid_artifact_filename"
    job, _manifest = assert_failed_evaluation_job(
        tmp_path,
        run_id,
        step_id="invalid-artifact-filename-evaluation",
        diagnostic_code="evaluation_invalid_artifact_filename",
    )
    assert job.output_artifact_ids == []


def test_evaluation_sdk_keeps_partial_proposal_out_of_executable_refs(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)

    with pytest.raises(ValidationFailed) as error:
        execute_evaluation_step(
            run_id=run_id,
            workspace=tmp_path,
            step=ProposalThenFailEvaluationStep(),
        )

    assert error.value.diagnostics[0].code == "fake_after_proposal_failed"
    job, manifest = assert_failed_evaluation_job(
        tmp_path,
        run_id,
        step_id="proposal-then-fail-evaluation",
        diagnostic_code="fake_after_proposal_failed",
    )
    assert job.output_artifact_ids == ["partial-failed-proposal"]
    assert {artifact.id for artifact in manifest.artifact_refs} >= {
        "partial-failed-proposal",
        "proposal-then-fail-evaluation-job",
    }


def test_evaluation_sdk_persists_unexpected_exception_as_failed_job(
    tmp_path: Path,
) -> None:
    run_id = simulate(tmp_path)

    with pytest.raises(ValidationFailed) as error:
        execute_evaluation_step(
            run_id=run_id,
            workspace=tmp_path,
            step=UnexpectedEvaluationFailureStep(),
        )

    assert error.value.diagnostics[0].code == "evaluation_step_failed"
    job, manifest = assert_failed_evaluation_job(
        tmp_path,
        run_id,
        step_id="unexpected-evaluation",
        diagnostic_code="evaluation_step_failed",
    )
    assert job.output_artifact_ids == ["unexpected-evaluation-partial"]
    assert {artifact.id for artifact in manifest.artifact_refs} >= {
        "unexpected-evaluation-partial",
        "unexpected-evaluation-job",
    }

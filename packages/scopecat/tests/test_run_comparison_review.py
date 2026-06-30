from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.errors import ValidationFailed
from scopecat.models.artifact import Artifact
from scopecat.run_comparison import (
    RunComparisonReviewRecord,
    execute_run_comparison,
    list_run_comparisons,
    review_run_comparison,
)
from scopecat.runs import open_run_store
from tests.support.records import assert_artifact_ref, read_model
from tests.support.run_comparison import simulate


def test_list_and_review_run_comparison_updates_baseline_manifest(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulate(tmp_path)
    candidate_run_id = simulate(tmp_path)
    execute_run_comparison(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        workspace=tmp_path,
    )
    comparison_id = f"run-comparison-{candidate_run_id}-signal"
    result_path = (
        tmp_path / "runs" / baseline_run_id / "artifacts" / f"{comparison_id}.json"
    )
    comparison_before_review = result_path.read_text()

    views_before = list_run_comparisons(run_id=baseline_run_id, workspace=tmp_path)
    assert len(views_before) == 1
    assert views_before[0].id == comparison_id
    assert views_before[0].review_status == "not_reviewed"

    result, review = review_run_comparison(
        run_id=baseline_run_id,
        selector=comparison_id,
        workspace=tmp_path,
        state="accepted",
        reviewer="operator",
        note="candidate is equivalent",
    )

    assert result.comparison_id == comparison_id
    assert review.decision == "accepted"
    assert review.reviewer == "operator"
    assert review.note == "candidate is equivalent"
    assert result_path.read_text() == comparison_before_review
    review_path = (
        tmp_path / "runs" / baseline_run_id / "reviews" / f"{comparison_id}.review.json"
    )
    assert review_path.is_file()
    stored_review = read_model(review_path, RunComparisonReviewRecord)
    assert stored_review == review
    assert stored_review.schema_version == "scopecat.run_comparison_review_record.v0"
    assert stored_review.run_id == baseline_run_id
    assert stored_review.comparison_ref == f"artifacts/{comparison_id}.json"

    views_after = list_run_comparisons(run_id=baseline_run_id, workspace=tmp_path)
    assert views_after[0].review_status == "reviewed"

    manifest = open_run_store(tmp_path).read_manifest(baseline_run_id)
    assert_artifact_ref(
        manifest.artifact_refs,
        f"{comparison_id}-review",
        kind="run_comparison_review_record",
        path=f"reviews/{comparison_id}.review.json",
    )


def test_review_run_comparison_rejected_works_on_independent_run(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulate(tmp_path)
    candidate_run_id = simulate(tmp_path)
    execute_run_comparison(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        workspace=tmp_path,
    )

    _result, review = review_run_comparison(
        run_id=baseline_run_id,
        selector=f"artifacts/run-comparison-{candidate_run_id}-signal.json",
        workspace=tmp_path,
        state="rejected",
        reviewer="operator",
        note="not suitable",
    )

    assert review.decision == "rejected"


def test_review_run_comparison_already_reviewed_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulate(tmp_path)
    candidate_run_id = simulate(tmp_path)
    comparison_id = f"run-comparison-{candidate_run_id}-signal"
    execute_run_comparison(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        workspace=tmp_path,
    )
    review_run_comparison(
        run_id=baseline_run_id,
        selector=comparison_id,
        workspace=tmp_path,
        state="accepted",
        reviewer="operator",
        note="first decision",
    )

    with pytest.raises(ValidationFailed) as error:
        review_run_comparison(
            run_id=baseline_run_id,
            selector=comparison_id,
            workspace=tmp_path,
            state="rejected",
            reviewer="operator",
            note="second decision",
        )

    assert error.value.diagnostics[0].code == "run_comparison_already_reviewed"


def test_review_run_comparison_missing_selector_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulate(tmp_path)
    candidate_run_id = simulate(tmp_path)
    execute_run_comparison(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        workspace=tmp_path,
    )

    with pytest.raises(ValidationFailed) as error:
        review_run_comparison(
            run_id=baseline_run_id,
            selector="missing-comparison",
            workspace=tmp_path,
            state="accepted",
            reviewer="operator",
            note="",
        )

    assert error.value.diagnostics[0].code == "run_comparison_not_found"


def test_review_run_comparison_path_escape_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulate(tmp_path)

    with pytest.raises(ValidationFailed) as error:
        review_run_comparison(
            run_id=baseline_run_id,
            selector="../escape.json",
            workspace=tmp_path,
            state="accepted",
            reviewer="operator",
            note="",
        )

    assert error.value.diagnostics[0].code == "run_comparison_path_escape"


def test_review_run_comparison_directory_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulate(tmp_path)
    candidate_run_id = simulate(tmp_path)
    comparison_id = f"run-comparison-{candidate_run_id}-signal"
    execute_run_comparison(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        workspace=tmp_path,
    )
    comparison_path = (
        tmp_path / "runs" / baseline_run_id / "artifacts" / f"{comparison_id}.json"
    )
    comparison_path.unlink()
    comparison_path.mkdir()

    with pytest.raises(ValidationFailed) as error:
        review_run_comparison(
            run_id=baseline_run_id,
            selector=comparison_id,
            workspace=tmp_path,
            state="accepted",
            reviewer="operator",
            note="",
        )

    assert error.value.diagnostics[0].code == "run_comparison_is_directory"


def test_review_run_comparison_invalid_json_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulate(tmp_path)
    candidate_run_id = simulate(tmp_path)
    comparison_id = f"run-comparison-{candidate_run_id}-signal"
    execute_run_comparison(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        workspace=tmp_path,
    )
    (
        tmp_path / "runs" / baseline_run_id / "artifacts" / f"{comparison_id}.json"
    ).write_text("{}\n")

    with pytest.raises(ValidationFailed) as error:
        review_run_comparison(
            run_id=baseline_run_id,
            selector=comparison_id,
            workspace=tmp_path,
            state="accepted",
            reviewer="operator",
            note="",
        )

    assert error.value.diagnostics[0].code == "invalid_run_comparison"


def test_review_run_comparison_wrong_artifact_kind_reports_stable_diagnostic(
    tmp_path: Path,
) -> None:
    baseline_run_id = simulate(tmp_path)
    storage = open_run_store(tmp_path)
    manifest = storage.read_manifest(baseline_run_id)
    manifest.artifact_refs.append(
        Artifact(
            id="not-comparison",
            kind="summary",
            path="artifacts/runner-adapter.summary.md",
            media_type="text/markdown",
        )
    )
    storage.write_manifest(manifest)

    with pytest.raises(ValidationFailed) as error:
        review_run_comparison(
            run_id=baseline_run_id,
            selector="not-comparison",
            workspace=tmp_path,
            state="accepted",
            reviewer="operator",
            note="",
        )

    assert error.value.diagnostics[0].code == "invalid_run_comparison"

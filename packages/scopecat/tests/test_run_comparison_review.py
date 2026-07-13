from __future__ import annotations

from pathlib import Path

import pytest

from scopecat._storage.refs import record_content_ref
from scopecat.errors import CheckFailed, Conflict, DataIntegrityError
from scopecat.run_comparison import (
    execute_run_comparison,
    list_run_comparisons,
    review_run_comparison,
)
from scopecat.runs import open_run_store
from tests.support.run_comparison import run_signal_experiment


def test_list_and_review_run_comparison_updates_baseline_manifest(
    tmp_path: Path,
) -> None:
    baseline_run_id, comparison_id = _write_comparison(tmp_path)

    views_before = list_run_comparisons(run_id=baseline_run_id, workspace=tmp_path)
    result, review = review_run_comparison(
        run_id=baseline_run_id,
        selector=comparison_id,
        workspace=tmp_path,
        state="accepted",
        reviewer="operator",
        note="candidate is equivalent",
    )
    views_after = list_run_comparisons(run_id=baseline_run_id, workspace=tmp_path)

    assert views_before[0].review_status == "not_reviewed"
    assert result.comparison_id == comparison_id
    assert review.decision == "accepted"
    assert views_after[0].review_status == "reviewed"


def test_review_run_comparison_rejected_works_on_record_selector(
    tmp_path: Path,
) -> None:
    baseline_run_id, comparison_id = _write_comparison(tmp_path)

    _result, review = review_run_comparison(
        run_id=baseline_run_id,
        selector=f"{comparison_id}-result",
        workspace=tmp_path,
        state="rejected",
        reviewer="operator",
        note="not suitable",
    )

    assert review.decision == "rejected"


def test_review_run_comparison_rejects_second_review(tmp_path: Path) -> None:
    baseline_run_id, comparison_id = _write_comparison(tmp_path)
    review_run_comparison(
        run_id=baseline_run_id,
        selector=comparison_id,
        workspace=tmp_path,
        state="accepted",
        reviewer="operator",
        note="first decision",
    )

    with pytest.raises(Conflict) as error:
        review_run_comparison(
            run_id=baseline_run_id,
            selector=comparison_id,
            workspace=tmp_path,
            state="rejected",
            reviewer="operator",
            note="second decision",
        )

    assert error.value.problems[0].code == "run_comparison_already_reviewed"


def test_review_run_comparison_rejects_path_escape(tmp_path: Path) -> None:
    baseline_run_id = run_signal_experiment(tmp_path)

    with pytest.raises(CheckFailed) as error:
        review_run_comparison(
            run_id=baseline_run_id,
            selector="../escape.json",
            workspace=tmp_path,
            state="accepted",
            reviewer="operator",
            note="",
        )

    assert error.value.problems[0].code == "run_comparison_path_escape"


def test_review_run_comparison_rejects_invalid_json(tmp_path: Path) -> None:
    baseline_run_id, comparison_id = _write_comparison(tmp_path)
    open_run_store(tmp_path).ref_path(
        baseline_run_id,
        record_content_ref(
            record_id=f"{comparison_id}-result",
            kind="run_comparison_result",
        ),
    ).write_text("{}\n")

    with pytest.raises(DataIntegrityError) as error:
        review_run_comparison(
            run_id=baseline_run_id,
            selector=comparison_id,
            workspace=tmp_path,
            state="accepted",
            reviewer="operator",
            note="",
        )

    assert error.value.problems[0].code == "invalid_run_comparison"


def _write_comparison(tmp_path: Path) -> tuple[str, str]:
    baseline_run_id = run_signal_experiment(tmp_path)
    candidate_run_id = run_signal_experiment(tmp_path)
    execute_run_comparison(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        workspace=tmp_path,
    )
    return baseline_run_id, f"run-comparison-{candidate_run_id}-signal"

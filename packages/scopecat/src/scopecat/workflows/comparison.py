"""Run comparison workflow use cases."""

from __future__ import annotations

from pathlib import Path

from scopecat.run_comparison import (
    RunComparisonReviewState,
    RunComparisonView,
    execute_run_comparison,
)
from scopecat.run_comparison import (
    list_run_comparisons as list_run_comparisons_impl,
)
from scopecat.run_comparison import (
    review_run_comparison as review_run_comparison_impl,
)
from scopecat.workflows._types import CompareRunsResult, ReviewRunComparisonResult


def compare_runs(
    *,
    baseline_run_id: str,
    candidate_run_id: str,
    workspace: str | Path,
    observable_id: str | None = None,
) -> CompareRunsResult:
    job, result = execute_run_comparison(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        workspace=workspace,
        observable_id=observable_id,
    )
    return CompareRunsResult(job=job, result=result)


def list_run_comparisons(
    *,
    run_id: str,
    workspace: str | Path,
) -> list[RunComparisonView]:
    return list_run_comparisons_impl(run_id=run_id, workspace=workspace)


def review_run_comparison(
    *,
    run_id: str,
    selector: str,
    workspace: str | Path,
    state: RunComparisonReviewState,
    reviewer: str,
    note: str = "",
) -> ReviewRunComparisonResult:
    result, review = review_run_comparison_impl(
        run_id=run_id,
        selector=selector,
        workspace=workspace,
        state=state,
        reviewer=reviewer,
        note=note,
    )
    return ReviewRunComparisonResult(result=result, review=review)

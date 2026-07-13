"""Run comparison workflow use cases."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.application.services import WorkspaceServices
from scopecat.run_comparison import (
    RunComparisonResult,
    RunComparisonReviewRecord,
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


@dataclass(frozen=True)
class ReviewRunComparisonResult:
    result: RunComparisonResult
    review: RunComparisonReviewRecord


def compare_runs(
    *,
    baseline_run_id: str,
    candidate_run_id: str,
    services: WorkspaceServices,
    observable_id: str | None = None,
) -> RunComparisonResult:
    return execute_run_comparison(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        services=services,
        observable_id=observable_id,
    )


def list_run_comparisons(
    *,
    run_id: str,
    services: WorkspaceServices,
) -> list[RunComparisonView]:
    return list_run_comparisons_impl(run_id=run_id, services=services)


def review_run_comparison(
    *,
    run_id: str,
    selector: str,
    services: WorkspaceServices,
    state: RunComparisonReviewState,
    reviewer: str,
    note: str = "",
) -> ReviewRunComparisonResult:
    result, review = review_run_comparison_impl(
        run_id=run_id,
        selector=selector,
        services=services,
        state=state,
        reviewer=reviewer,
        note=note,
    )
    return ReviewRunComparisonResult(result=result, review=review)

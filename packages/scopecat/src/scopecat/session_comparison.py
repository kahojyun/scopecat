"""Run comparison facade handles for notebook workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from scopecat.run_comparison import RunComparisonReviewState
from scopecat.workflows import CompareRunsResult, ReviewRunComparisonResult
from scopecat.workflows.comparison import review_run_comparison


class ComparisonSession(Protocol):
    @property
    def workspace(self) -> Path: ...

    @property
    def reviewer(self) -> str: ...


@dataclass(frozen=True)
class ComparisonHandle:
    session: ComparisonSession
    baseline_run_id: str
    workflow: CompareRunsResult

    @property
    def result(self):
        return self.workflow.result

    @property
    def id(self) -> str:
        return self.workflow.result.comparison_id

    def review(
        self,
        *,
        state: RunComparisonReviewState,
        reviewer: str | None = None,
        note: str = "",
    ) -> ReviewRunComparisonResult:
        return review_run_comparison(
            run_id=self.baseline_run_id,
            selector=self.id,
            workspace=self.session.workspace,
            state=state,
            reviewer=reviewer or self.session.reviewer,
            note=note,
        )


__all__ = ["ComparisonHandle"]

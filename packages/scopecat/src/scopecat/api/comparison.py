"""Run comparison facade handles for notebook workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from scopecat.api._services import workspace_services
from scopecat.application.services import WorkspaceServices
from scopecat.run_comparison import RunComparisonResult, RunComparisonReviewState
from scopecat.run_comparison.service import (
    ReviewRunComparisonResult,
    review_run_comparison,
)


class ComparisonSession(Protocol):
    @property
    def _services(self) -> WorkspaceServices: ...

    @property
    def reviewer(self) -> str: ...


@dataclass(frozen=True)
class ComparisonHandle:
    session: ComparisonSession
    baseline_run_id: str
    result: RunComparisonResult

    @property
    def id(self) -> str:
        return self.result.comparison_id

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
            services=workspace_services(self.session),
            state=state,
            reviewer=reviewer or self.session.reviewer,
            note=note,
        )


__all__ = ["ComparisonHandle"]

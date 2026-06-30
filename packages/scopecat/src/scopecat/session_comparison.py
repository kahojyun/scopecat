"""Run comparison facade handles for notebook workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from scopecat.run_comparison import RunComparisonReviewState
from scopecat.workflows import CompareRunsResult, ReviewRunComparisonResult

if TYPE_CHECKING:
    from scopecat.client import Client


class ComparisonSession(Protocol):
    @property
    def client(self) -> Client: ...

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
        return self.session.client.review_comparison(
            self.baseline_run_id,
            self.id,
            state=state,
            reviewer=reviewer or self.session.reviewer,
            note=note,
        )


__all__ = ["ComparisonHandle"]

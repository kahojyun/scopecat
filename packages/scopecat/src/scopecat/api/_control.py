"""Operator control-plane operations for one daemon."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.control.models import ControlRunState, EventPage
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.views import (
    DaemonHealth,
    MeasurementPage,
    RunDetail,
    RunSummaryPage,
)
from scopecat.daemon.wire import (
    AttentionResolutionReceipt,
)


@dataclass(frozen=True, slots=True)
class LabControlOperations:
    """Browsing, admission, and attention controls for operators."""

    client: DaemonClient

    def health(self) -> DaemonHealth:
        return self.client.health()

    def runs(
        self,
        *,
        limit: int = 50,
        before: int | None = None,
        state: ControlRunState | None = None,
    ) -> RunSummaryPage:
        return self.client.list_runs(
            limit=limit,
            before=before,
            state=state,
        )

    def run_detail(self, run_id: str) -> RunDetail:
        return self.client.get_run(run_id)

    def events(
        self,
        *,
        limit: int = 100,
        after: int | None = None,
        run_id: str | None = None,
        latest: bool = True,
    ) -> EventPage:
        return self.client.replay_events(
            limit=limit,
            after=after,
            run_id=run_id,
            latest=latest,
        )

    def measurements(
        self,
        run_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> MeasurementPage:
        return self.client.measurements(run_id, limit=limit, offset=offset)

    def resolve_attention(
        self,
        run_id: str,
    ) -> AttentionResolutionReceipt:
        return self.client.resolve_attention(run_id)


__all__ = ["LabControlOperations"]

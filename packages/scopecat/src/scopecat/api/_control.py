"""Operator control-plane operations for one daemon."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.control.models import ControlRunState, EventPage
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.views import (
    DaemonHealth,
    MeasurementTracePreview,
    MeasurementTracePreviewQuery,
    RunDetail,
    RunSummaryPage,
)
from scopecat.daemon.wire import (
    AttentionResolutionCommand,
    AttentionResolutionReceipt,
    RunCancellationReceipt,
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
        sample_id: str | None = None,
    ) -> RunSummaryPage:
        return self.client.list_runs(
            limit=limit,
            before=before,
            state=state,
            sample_id=sample_id,
        )

    def run_detail(self, run_id: str) -> RunDetail:
        return self.client.get_run(run_id)

    def cancel(self, run_id: str) -> RunCancellationReceipt:
        """Cancel queued work or request a safe stop from its active executor."""

        return self.client.cancel_run(run_id)

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

    def measurement_trace_preview(
        self,
        run_id: str,
        query: MeasurementTracePreviewQuery,
    ) -> MeasurementTracePreview:
        return self.client.measurement_trace_preview(run_id, query)

    def resolve_attention(
        self,
        run_id: str,
        command: AttentionResolutionCommand,
    ) -> AttentionResolutionReceipt:
        return self.client.resolve_attention(run_id, command)


__all__ = ["LabControlOperations"]

"""Operator control-plane operations for one daemon."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from scopecat.control.models import ControlRunState, EventPage, RunPage
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.views import DaemonHealth, MeasurementPage, RunDetail
from scopecat.daemon.wire import (
    AttentionResolutionAction,
    AttentionResolutionReceipt,
    ExperimentCatalog,
    ManagedRunSubmission,
    RunAdmission,
)
from scopecat.records.run_request import RunRequest


@dataclass(frozen=True, slots=True)
class LabControlOperations:
    """Browsing, admission, and attention controls for operators."""

    client: DaemonClient

    def health(self) -> DaemonHealth:
        return self.client.health()

    def catalog(self) -> ExperimentCatalog:
        return self.client.catalog()

    def runs(
        self,
        *,
        limit: int = 50,
        after: int | None = None,
        before: int | None = None,
        state: ControlRunState | None = None,
        latest: bool | None = None,
    ) -> RunPage:
        return self.client.list_runs(
            limit=limit,
            after=after,
            before=before,
            state=state,
            latest=(after is None and before is None if latest is None else latest),
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
        action: AttentionResolutionAction,
    ) -> AttentionResolutionReceipt:
        return self.client.resolve_attention(run_id, action)

    def submit_managed(
        self,
        registration_id: str,
        registration_version: str,
        request: RunRequest,
        *,
        submission_id: str | None = None,
    ) -> RunAdmission:
        return self.client.submit_managed(
            ManagedRunSubmission(
                submission_id=submission_id or uuid4().hex,
                registration_id=registration_id,
                registration_version=registration_version,
                request=request,
            )
        )


__all__ = ["LabControlOperations"]

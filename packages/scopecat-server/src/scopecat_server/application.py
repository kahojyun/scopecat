"""Daemon application composition root."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from scopecat.daemon.views import DaemonHealth
from scopecat.daemon.wire import (
    AttentionResolutionReceipt,
    RunAdmission,
    RunCancellationReceipt,
    RunSubmission,
)

from scopecat_server.storage.sqlite import SQLiteProjectStore

from .admission_service import AdmissionService
from .config_service import ConfigService
from .executor_service import ExecutorService
from .instrument_service import InstrumentService
from .lease_supervisor import OwnershipLeaseSupervisor
from .payload_service import CommandPayloadService
from .run_service import RunService


class DaemonApplication:
    """Composition root exposing narrow services to the transport."""

    def __init__(
        self,
        *,
        project_root: str | Path,
        project_id: str,
        project_store: SQLiteProjectStore,
        config: ConfigService,
        runs: RunService,
        admission: AdmissionService,
        executor: ExecutorService,
        instruments: InstrumentService,
        payloads: CommandPayloadService,
        lease_supervisor: OwnershipLeaseSupervisor,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.project_id = project_id
        self._project_store = project_store
        self.config = config
        self.runs = runs
        self._admission = admission
        self.executor = executor
        self.instruments = instruments
        self.payloads = payloads
        self._lease_supervisor = lease_supervisor

    def start(self) -> None:
        self._lease_supervisor.start()

    def close(self) -> None:
        self._lease_supervisor.request_stop()
        try:
            self.instruments.shutdown()
        finally:
            self._lease_supervisor.close()

    def health(self) -> DaemonHealth:
        try:
            self._project_store.schema_version()
        except Exception:
            status: Literal["ok", "degraded"] = "degraded"
        else:
            status = (
                "ok"
                if self._lease_supervisor.healthy and self.instruments.healthy
                else "degraded"
            )
        return DaemonHealth(
            status=status,
            project_id=self.project_id,
            project_name=self.project_root.name,
            project_root=str(self.project_root),
        )

    def submit_run(self, submission: RunSubmission) -> RunAdmission:
        return self._admission.submit_run(submission)

    def cancel_run(self, run_id: str) -> RunCancellationReceipt:
        return self.executor.cancel_run(run_id)

    def resolve_attention(
        self,
        run_id: str,
    ) -> AttentionResolutionReceipt:
        return self.instruments.resolve_run_attention(
            run_id,
            self._admission.resolve_attention,
        )

"""Daemon application composition root."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from scopecat.adapters.sqlite import SQLiteProjectStore
from scopecat.daemon.views import DaemonHealth
from scopecat.daemon.wire import (
    AttentionResolutionReceipt,
    RunAdmission,
    RunSubmission,
)

from .admission_service import AdmissionService
from .config_service import ConfigService
from .executor_service import ExecutorService
from .lease_supervisor import ExecutorLeaseSupervisor
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
        lease_supervisor: ExecutorLeaseSupervisor,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.project_id = project_id
        self._project_store = project_store
        self.config = config
        self.runs = runs
        self._admission = admission
        self.executor = executor
        self._lease_supervisor = lease_supervisor

    def start(self) -> None:
        self._lease_supervisor.start()

    def close(self) -> None:
        self._lease_supervisor.close()

    def health(self) -> DaemonHealth:
        try:
            self._project_store.schema_version()
        except Exception:
            status: Literal["ok", "degraded"] = "degraded"
        else:
            status = "ok" if self._lease_supervisor.healthy else "degraded"
        return DaemonHealth(
            status=status,
            project_id=self.project_id,
            project_name=self.project_root.name,
            project_root=str(self.project_root),
        )

    def submit_run(self, submission: RunSubmission) -> RunAdmission:
        return self._admission.submit_run(submission)

    def resolve_attention(
        self,
        run_id: str,
    ) -> AttentionResolutionReceipt:
        return self._admission.resolve_attention(run_id)

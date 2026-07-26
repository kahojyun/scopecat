"""Local planning and execution for daemon-admitted scratch runs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Event, Lock, Thread
from typing import override
from uuid import uuid4

from scopecat.authoring import MetadataValue
from scopecat.authoring.templates import ExperimentInvocation
from scopecat.control.models import ResourceKey, RunPlanSummary
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.execution import (
    ExecutorLeaseLostError,
    LeaseSupervisor,
    daemon_execution_session,
)
from scopecat.daemon.wire import (
    ExecutorLease,
    RunSubmission,
)
from scopecat.execution.interpreter import execute_admitted_run
from scopecat.planning.preview import build_run_program_preview
from scopecat.planning.preview_models import ExperimentPreview
from scopecat.planning.service import PlannedRun, plan_scratch_experiment
from scopecat.planning.system import (
    ExperimentSystemBuilder,
    build_experiment_system,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import (
    ConfigRegistryRunConfigSource,
    RunConfigSource,
    RunManifest,
)


@dataclass(frozen=True, slots=True)
class _DaemonRunner:
    client: DaemonClient
    build_system: ExperimentSystemBuilder | None

    def execute(
        self,
        planned: PlannedRun,
        *,
        executor_id: str = "notebook",
        submission_id: str | None = None,
    ) -> RunManifest:
        """Admit a plan remotely while executing its Python closures locally."""

        submission = RunSubmission(
            submission_id=submission_id or uuid4().hex,
            config=planned.config,
            config_source=planned.config_source,
            request=planned.request,
            plan=_run_plan_summary(planned),
        )
        admission = self.client.submit_run(submission)
        heartbeat = _LeaseHeartbeat()
        session = daemon_execution_session(
            self.client,
            submission,
            admission,
            executor_id=executor_id,
            lease_supervisor=heartbeat,
        )
        try:
            return execute_admitted_run(
                program=planned.program,
                session=session,
                instrument_provider=(
                    None if planned.system is None else planned.system.provider
                ),
            )
        finally:
            heartbeat.close()

    def run(
        self,
        experiment: ExperimentInvocation,
        *,
        config: ConfigProfileSnapshot | None = None,
        config_source: RunConfigSource | None = None,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
        executor_id: str = "notebook",
        submission_id: str | None = None,
    ) -> RunManifest:
        planned = self._plan(
            experiment,
            config=config,
            config_source=config_source,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )
        return self.execute(
            planned,
            executor_id=executor_id,
            submission_id=submission_id,
        )

    def preview(
        self,
        experiment: ExperimentInvocation,
        *,
        config: ConfigProfileSnapshot | None = None,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> ExperimentPreview:
        planned = self._plan(
            experiment,
            config=config,
            config_source=None,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )
        return build_run_program_preview(planned.program)

    def _plan(
        self,
        experiment: ExperimentInvocation,
        *,
        config: ConfigProfileSnapshot | None,
        config_source: RunConfigSource | None,
        name: str | None,
        tags: tuple[str, ...],
        description: str | None,
        metadata: Mapping[str, MetadataValue] | None,
        operator: str | None,
    ) -> PlannedRun:
        selected_source = config_source
        if config is None:
            active = self.client.active_config()
            selected_config = active.config
            selected_source = selected_source or ConfigRegistryRunConfigSource(
                selector="active",
                entry_id=active.entry.id,
                config_ref=active.entry.config_ref,
                content_hash=active.entry.content_hash,
                registry_generation=active.active_state.generation,
            )
        else:
            selected_config = config
        selected_system = build_experiment_system(
            self.build_system,
            selected_config,
        )
        if selected_system is None:
            raise ValueError("scratch execution requires an experiment system")
        selected_metadata = dict(metadata or {})
        if name is not None:
            selected_metadata["name"] = name
        if tags:
            selected_metadata["tags"] = list(tags)
        if description is not None:
            selected_metadata["description"] = description
        return plan_scratch_experiment(
            experiment,
            config=selected_config,
            system=selected_system,
            config_source=selected_source,
            metadata=selected_metadata,
            operator=operator,
        )


class _LeaseHeartbeat(LeaseSupervisor):
    def __init__(self) -> None:
        self._stop = Event()
        self._lock = Lock()
        self._failure: tuple[ExecutorLease, Exception] | None = None
        self._thread: Thread | None = None

    @override
    def start(
        self,
        lease: ExecutorLease,
        heartbeat: Callable[[], ExecutorLease],
    ) -> None:
        self._thread = Thread(
            target=self._run,
            args=(lease, heartbeat),
            name=f"scopecat-lease-{lease.run_id}",
            daemon=True,
        )
        self._thread.start()

    @override
    def require_live(self) -> None:
        with self._lock:
            failure = self._failure
        if failure is not None:
            lease, cause = failure
            raise ExecutorLeaseLostError(lease, cause) from cause

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def _run(
        self,
        lease: ExecutorLease,
        heartbeat: Callable[[], ExecutorLease],
    ) -> None:
        current = lease
        while not self._stop.wait(current.heartbeat_interval_seconds):
            try:
                current = heartbeat()
            except Exception as error:
                with self._lock:
                    self._failure = (current, error)
                return


def _run_plan_summary(planned: PlannedRun) -> RunPlanSummary:
    program = planned.program
    return RunPlanSummary(
        experiment_id=program.experiment_id,
        experiment_kind=program.points.experiment_kind,
        point_count=len(program.points.points),
        coordinate_ids=program.measurements.coordinate_ids,
        record_ids=tuple(record.id for record in program.measurements.records),
        run_resource_claims=tuple(
            ResourceKey(id=claim.id, kind=claim.kind)
            for claim in program.resource_claims
        ),
    )


__all__ = ["_DaemonRunner"]

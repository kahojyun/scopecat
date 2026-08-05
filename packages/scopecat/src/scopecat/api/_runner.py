"""Local planning and execution for daemon-admitted experiment invocations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from threading import Event, Lock, Thread
from time import monotonic
from typing import override
from uuid import uuid4

import httpx2

from scopecat.authoring import MetadataValue
from scopecat.authoring.experiments import ExperimentInvocation
from scopecat.control.models import (
    RunDomainTargetRequirement,
    RunPlanSummary,
    RunResourceRequirement,
)
from scopecat.daemon.client import (
    DaemonClient,
    DaemonUnavailableError,
)
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
from scopecat.planning.provider_validation import instrument_contract_fingerprint
from scopecat.planning.service import PlannedRun, plan_experiment_invocation
from scopecat.planning.system import (
    ExperimentSystemBuilder,
    build_experiment_system,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import (
    ConfigRegistryRunConfigSource,
    RunConfigSource,
    RunManifest,
    RunStageLineage,
)


@dataclass(frozen=True, slots=True)
class _DaemonRunner:
    client: DaemonClient
    build_experiment_system: ExperimentSystemBuilder | None

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
        stage: RunStageLineage | None = None,
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
            stage=stage,
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
            stage=None,
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
        stage: RunStageLineage | None,
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
                registry_generation=active.activation.generation,
            )
        else:
            selected_config = config
        instrument_catalog = self.client.resolve_instrument_contracts(
            selected_config,
        )
        selected_system = build_experiment_system(
            self.build_experiment_system,
            selected_config,
            instrument_catalog,
        )
        selected_metadata = dict(metadata or {})
        if name is not None:
            selected_metadata["name"] = name
        if tags:
            selected_metadata["tags"] = list(tags)
        if description is not None:
            selected_metadata["description"] = description
        planned = plan_experiment_invocation(
            experiment,
            config=selected_config,
            system=selected_system,
            config_source=selected_source,
            metadata=selected_metadata,
            operator=operator,
        )
        if stage is None:
            return planned
        return replace(
            planned,
            request=planned.request.model_copy(update={"stage": stage}),
        )


class _LeaseHeartbeat(LeaseSupervisor):
    def __init__(self) -> None:
        self._stop = Event()
        self._lock = Lock()
        self._failure: tuple[ExecutorLease, Exception] | None = None
        self._cancellation_requested = Event()
        self._thread: Thread | None = None

    @override
    def start(
        self,
        lease: ExecutorLease,
        heartbeat: Callable[[], ExecutorLease],
    ) -> None:
        if lease.cancellation_requested_at is not None:
            self._cancellation_requested.set()
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

    @override
    def cancellation_requested(self) -> bool:
        return self._cancellation_requested.is_set()

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
        deadline, delay = _executor_lease_timing(current)
        while not self._stop.wait(delay):
            try:
                current = heartbeat()
                if current.cancellation_requested_at is not None:
                    self._cancellation_requested.set()
            except Exception as error:
                if isinstance(error, (DaemonUnavailableError, httpx2.TransportError)):
                    remaining = deadline - monotonic()
                    if remaining > 0:
                        delay = min(
                            0.25, current.heartbeat_interval_seconds / 2, remaining
                        )
                        continue
                with self._lock:
                    self._failure = (current, error)
                return
            deadline, delay = _executor_lease_timing(current)


def _executor_lease_timing(lease: ExecutorLease) -> tuple[float, float]:
    now = datetime.now(UTC)
    interval = lease.heartbeat_interval_seconds
    remaining = max((lease.expires_at - now).total_seconds(), 0.0)
    renewal_at = lease.expires_at - timedelta(seconds=interval * 2)
    delay = max((renewal_at - now).total_seconds(), 0.0)
    return monotonic() + remaining, delay


def _run_plan_summary(planned: PlannedRun) -> RunPlanSummary:
    program = planned.program
    host = program.host
    descriptions = (
        ()
        if host is None
        else tuple(
            host.advertised_descriptions[instrument_id]
            for instrument_id in host.resource_order
        )
    )
    return RunPlanSummary(
        experiment_id=program.experiment_id,
        experiment_kind=program.points.experiment_kind,
        point_count=len(program.points.points),
        coordinate_ids=program.measurements.coordinate_ids,
        record_ids=tuple(record.id for record in program.measurements.records),
        host_instrument_order=program.resource_order,
        host_provider_id=None if host is None else host.provider_id,
        host_contract_fingerprint=(
            None
            if host is None
            else instrument_contract_fingerprint(host.provider_id, descriptions)
        ),
        domain_target_requirement=(
            None
            if program.domain_target_requirement is None
            else RunDomainTargetRequirement(
                id=program.domain_target_requirement.id,
                kind=program.domain_target_requirement.kind,
                instrument_ids=program.domain_target_requirement.instrument_ids,
            )
        ),
        run_resource_requirements=tuple(
            RunResourceRequirement(
                id=requirement.id,
                kind=requirement.kind,
            )
            for requirement in program.resource_requirements
        ),
    )


__all__ = ["_DaemonRunner"]

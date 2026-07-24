"""Local planning and execution for daemon-admitted scratch runs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from threading import Event, Lock, Thread
from typing import override
from uuid import uuid4

from scopecat.authoring import MetadataValue
from scopecat.authoring.templates import ExperimentInvocation
from scopecat.compiler.frontend.invocation import (
    PreparedInvocation,
    prepare_invocation,
)
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.execution import (
    DelegatedExecutorLeaseLostError,
    DelegatedLeaseSupervisor,
    delegated_execution_services,
)
from scopecat.daemon.wire import (
    DelegatedPlanSummary,
    DelegatedRunSubmission,
    ExecutorLease,
    ResourceClaimDescriptor,
)
from scopecat.execution.interpreter import execute_admitted_run
from scopecat.execution.observation import (
    RuntimeEvent,
    RuntimeEventSink,
    RuntimePayloadObserver,
)
from scopecat.planning.preview import build_run_program_preview
from scopecat.planning.preview_models import ExperimentPreview
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
from scopecat.runs.service import PlannedRun, plan_scratch_experiment


@dataclass(frozen=True, slots=True)
class _DelegatedRunner:
    client: DaemonClient
    build_system: ExperimentSystemBuilder | None

    def execute(
        self,
        planned: PlannedRun,
        *,
        executor_id: str = "notebook",
        submission_id: str | None = None,
        event_sink: RuntimeEventSink | None = None,
        payload_observer: RuntimePayloadObserver | None = None,
    ) -> RunManifest:
        """Admit a plan remotely while executing its Python closures locally."""

        if planned.request is None:
            raise ValueError("delegated execution requires a durable run request")
        submission = DelegatedRunSubmission(
            submission_id=submission_id or uuid4().hex,
            executor_id=executor_id,
            config=planned.config,
            config_source=planned.config_source,
            request=planned.request,
            plan=_delegated_plan_summary(planned),
        )
        admission = self.client.submit_delegated(submission)
        heartbeat = _LeaseHeartbeat()
        services = delegated_execution_services(
            self.client,
            submission,
            admission,
            lease_supervisor=heartbeat,
        )
        try:
            return execute_admitted_run(
                run_id=admission.run_id,
                program=planned.program,
                services=services,
                instrument_provider=(
                    None if planned.system is None else planned.system.provider
                ),
                event_sink=_combine_runtime_event_sinks(
                    services.runtime_event_sink,
                    event_sink,
                ),
                payload_observer=payload_observer,
            )
        finally:
            heartbeat.close()

    def run(
        self,
        experiment: ExperimentInvocation | PreparedInvocation,
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
        event_sink: RuntimeEventSink | None = None,
        payload_observer: RuntimePayloadObserver | None = None,
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
            event_sink=event_sink,
            payload_observer=payload_observer,
        )

    def preview(
        self,
        experiment: ExperimentInvocation | PreparedInvocation,
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
        experiment: ExperimentInvocation | PreparedInvocation,
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
        prepared = (
            experiment
            if isinstance(experiment, PreparedInvocation)
            else prepare_invocation(experiment)
        )
        return plan_scratch_experiment(
            _prepared_invocation_with_metadata(
                prepared,
                name=name,
                tags=tags,
                description=description,
                metadata=metadata,
                operator=operator,
            ),
            config=selected_config,
            system=selected_system,
            config_source=selected_source,
        )


def _prepared_invocation_with_metadata(
    prepared: PreparedInvocation,
    *,
    name: str | None,
    tags: tuple[str, ...],
    description: str | None,
    metadata: Mapping[str, MetadataValue] | None,
    operator: str | None,
) -> PreparedInvocation:
    selected_metadata = dict(prepared.request_context.metadata)
    selected_metadata.update(metadata or {})
    if name is not None:
        selected_metadata["name"] = name
    if tags:
        selected_metadata["tags"] = list(tags)
    if description is not None:
        selected_metadata["description"] = description
    return replace(
        prepared,
        request_context=replace(
            prepared.request_context,
            metadata=selected_metadata,
            operator=(
                prepared.request_context.operator if operator is None else operator
            ),
        ),
    )


def _combine_runtime_event_sinks(
    remote: RuntimeEventSink | None,
    local: RuntimeEventSink | None,
) -> RuntimeEventSink | None:
    if remote is None:
        return local
    if local is None:
        return remote

    def observe(event: RuntimeEvent) -> None:
        try:
            remote(event)
        finally:
            local(event)

    return observe


class _LeaseHeartbeat(DelegatedLeaseSupervisor):
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
            raise DelegatedExecutorLeaseLostError(lease, cause) from cause

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


def _delegated_plan_summary(planned: PlannedRun) -> DelegatedPlanSummary:
    preview = build_run_program_preview(planned.program)
    return DelegatedPlanSummary(
        experiment_id=preview.experiment_id,
        experiment_kind=preview.experiment_kind,
        point_count=preview.point_count,
        coordinate_ids=preview.coordinate_ids,
        record_ids=tuple(record.id for record in preview.records),
        run_resource_claims=tuple(
            ResourceClaimDescriptor(id=claim.id, kind=claim.kind)
            for claim in planned.program.resource_claims
        ),
    )


__all__ = ["_DelegatedRunner"]

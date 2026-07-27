"""Daemon-owned drivers for direct sessions and admitted experiment runs."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import timedelta
from threading import RLock
from typing import Literal

from pydantic import JsonValue
from scopecat.adapters.sqlite import (
    ControlPlaneConflict,
    ControlPlaneNotFound,
    ExecutorLeaseNotHeld,
    InstrumentSessionLeaseNotHeld,
    SQLiteControlPlane,
    SQLiteRunRepository,
)
from scopecat.control.models import (
    DurableEventInput,
    InstrumentSession,
    ResourceLease,
)
from scopecat.daemon.views import InstrumentListView, InstrumentView
from scopecat.daemon.wire import (
    InstrumentSessionApplyCommand,
    InstrumentSessionCollectCommand,
    InstrumentSessionEndCommand,
    InstrumentSessionEndReceipt,
    InstrumentSessionHeartbeat,
    InstrumentSessionLease,
    InstrumentSessionOpenCommand,
    InstrumentSessionReadCommand,
    RunInstrumentApplyCommand,
    RunInstrumentCollectCommand,
    RunInstrumentLifecycleCommand,
    RunInstrumentLifecycleReceipt,
    RunInstrumentProvisionCommand,
    RunInstrumentProvisionReceipt,
    RunInstrumentReadCommand,
)
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemPhase,
    RuntimeLocation,
    problem,
)
from scopecat.planning.provider_validation import (
    describe_instruments,
    validate_instruments,
)
from scopecat.planning.system import ExperimentSystemBuilder
from scopecat.records.config import (
    ConfigProfileSnapshot,
    InstrumentSpec,
    config_content_hash,
)
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.instruments.contracts import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProvider,
    InstrumentProviderContext,
    InstrumentStateCommand,
    validate_collect_command,
    validate_collect_receipt,
    validate_state_command,
)

from .config_service import ConfigService
from .errors import BackendConflict, BackendNotFound

_ENDED_SESSION_LIMIT = 256


@dataclass(slots=True)
class _OperationLedger:
    apply_receipts: dict[str, tuple[InstrumentStateCommand, ApplyReceipt]] = field(
        default_factory=dict
    )
    collect_receipts: dict[str, tuple[CollectCommand, CollectReceipt]] = field(
        default_factory=dict
    )
    collect_failures: dict[str, tuple[CollectCommand, str]] = field(
        default_factory=dict
    )
    run_operations: dict[str, _RunOperation] = field(default_factory=dict)


@dataclass(slots=True)
class _LiveDrivers:
    drivers: dict[str, InstrumentDriver]
    descriptions: dict[str, InstrumentDescription]
    ledger: _OperationLedger = field(default_factory=_OperationLedger)
    lock: RLock = field(default_factory=RLock)

    @property
    def apply_receipts(
        self,
    ) -> dict[str, tuple[InstrumentStateCommand, ApplyReceipt]]:
        return self.ledger.apply_receipts

    @property
    def collect_receipts(self) -> dict[str, tuple[CollectCommand, CollectReceipt]]:
        return self.ledger.collect_receipts

    @property
    def collect_failures(self) -> dict[str, tuple[CollectCommand, str]]:
        return self.ledger.collect_failures


@dataclass(frozen=True, slots=True)
class _EndedSession:
    command: InstrumentSessionEndCommand
    abort: bool
    receipt: InstrumentSessionEndReceipt


@dataclass(frozen=True, slots=True)
class _RunProvision:
    command: RunInstrumentProvisionCommand
    receipt: RunInstrumentProvisionReceipt
    ledger: _OperationLedger = field(default_factory=_OperationLedger)
    lock: RLock = field(default_factory=RLock, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class _RunOperation:
    kind: Literal["read", "apply", "collect", "lifecycle"]
    instrument_id: str
    command: (
        RunInstrumentReadCommand
        | RunInstrumentApplyCommand
        | RunInstrumentCollectCommand
        | RunInstrumentLifecycleCommand
    )
    result: (
        InstrumentStateSnapshot
        | ApplyReceipt
        | CollectReceipt
        | RunInstrumentLifecycleReceipt
        | None
    )
    failure: str | None = None


class InstrumentService:
    """Retain live drivers behind renewable daemon fencing tokens."""

    def __init__(
        self,
        *,
        control: SQLiteControlPlane,
        runs: SQLiteRunRepository,
        config: ConfigService,
        build_system: ExperimentSystemBuilder | None,
        lease_ttl: timedelta | None = None,
    ) -> None:
        self._control = control
        self._runs = runs
        self._config = config
        self._build_system = build_system
        self._lease_ttl = lease_ttl or timedelta(seconds=30)
        self._heartbeat_interval_seconds = self._lease_ttl.total_seconds() / 3
        self._sessions: dict[str, _LiveDrivers] = {}
        self._ended_sessions: OrderedDict[str, _EndedSession] = OrderedDict()
        self._ended_session_limit = _ENDED_SESSION_LIMIT
        self._run_runtimes: dict[str, _LiveDrivers] = {}
        self._run_provisions: dict[str, _RunProvision] = {}
        self._sessions_lock = RLock()
        self._open_lock = RLock()
        self._run_lock = RLock()
        self._run_open_locks: dict[str, RLock] = {}
        self._finalizing_runs: set[str] = set()
        self._attention_lock = RLock()
        self._provider_lock = RLock()
        self._provider_content_hash: str | None = None
        self._cached_provider: InstrumentProvider | None = None

    def list_instruments(self) -> InstrumentListView:
        active = self._config.get_active_config()
        descriptions, provider_problems = self._descriptions(active.config)
        global_problems, instrument_problems = _scope_provider_problems(
            active.config.instrument_registry.instruments,
            provider_problems,
        )
        with self._control.transaction() as connection:
            leases = {
                lease.resource.id: lease
                for lease in self._control.list_resource_leases_in_transaction(
                    connection
                )
                if lease.resource.kind == "instrument"
            }
        session_actors = {
            session.session_id: session.actor
            for session in self._control.list_instrument_sessions()
            if session.state != "closed"
        }
        items = tuple(
            self._instrument_view(
                spec,
                description=descriptions.get(spec.id),
                lease=leases.get(spec.id),
                owner_actor=(
                    session_actors.get(lease.owner_id)
                    if (
                        (lease := leases.get(spec.id)) is not None
                        and lease.owner_kind == "instrument_session"
                    )
                    else None
                ),
                problems=instrument_problems.get(spec.id, ()),
            )
            for spec in active.config.instrument_registry.instruments
        )
        return InstrumentListView(
            config_entry_id=active.entry.id,
            config_content_hash=active.entry.content_hash,
            items=items,
            problems=global_problems,
        )

    def get_instrument(self, instrument_id: str) -> InstrumentView:
        instruments = self.list_instruments()
        for item in instruments.items:
            if item.spec.id == instrument_id:
                return item
        raise BackendNotFound(f"instrument was not found: {instrument_id}")

    def provision_run(
        self,
        run_id: str,
        command: RunInstrumentProvisionCommand,
    ) -> RunInstrumentProvisionReceipt:
        """Connect the exact instrument claims admitted with one fenced run."""

        with self._run_operation_lock(run_id):
            return self._provision_run(run_id, command)

    def _provision_run(
        self,
        run_id: str,
        command: RunInstrumentProvisionCommand,
    ) -> RunInstrumentProvisionReceipt:
        self._fence_run(run_id, command.lease_id)
        if self._run_is_finalizing(run_id):
            raise BackendConflict("run instrument host is finalizing")
        cached = self._run_provision_state(run_id)
        if cached is not None:
            if cached.command != command:
                if cached.command.operation_id == command.operation_id:
                    raise BackendConflict(
                        "run instrument provision operation id has different content"
                    )
                raise BackendConflict("run instruments are already provisioned")
            return cached.receipt

        try:
            control_run = self._control.get_run(run_id)
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error
        instrument_claims = frozenset(
            claim.id
            for claim in control_run.admission.resource_claims
            if claim.kind == "instrument"
        )
        instrument_ids = control_run.admission.plan.host_instrument_order
        if not instrument_ids:
            receipt = RunInstrumentProvisionReceipt(
                run_id=run_id,
                operation_id=command.operation_id,
                status="ready",
            )
            self._store_run_provision(
                run_id,
                _RunProvision(
                    command=command,
                    receipt=receipt,
                    lock=self._run_operation_lock(run_id),
                ),
            )
            return receipt

        config = self._runs.read_config_profile_snapshot(run_id)
        try:
            provider = self._provider(config)
        except Exception as error:
            return self._reject_run_provision(
                run_id,
                command,
                problems=(
                    _provision_problem(
                        (
                            "instrument_provider_unavailable"
                            if isinstance(error, BackendConflict)
                            else "instrument_provider_construction_failed"
                        ),
                        "instrument provider could not be constructed",
                        run_id=run_id,
                        operation_id=command.operation_id,
                        details={"exception_type": type(error).__name__},
                    ),
                ),
            )
        provider_id = provider.provider_id

        try:
            provider_description = provider.describe(
                InstrumentProviderContext(
                    config=config,
                    instrument_ids=instrument_ids,
                )
            )
        except Exception:
            return self._reject_run_provision(
                run_id,
                command,
                problems=(
                    _provision_problem(
                        "instrument_provider_description_failed",
                        "instrument provider description failed",
                        run_id=run_id,
                        operation_id=command.operation_id,
                    ),
                ),
            )
        global_problems, instrument_problems = _scope_provider_problems(
            config.instrument_registry.instruments,
            provider_description.problems,
        )
        setup_problems = list(global_problems)
        setup_problems.extend(
            item
            for instrument_id in instrument_ids
            for item in instrument_problems.get(instrument_id, ())
        )
        if provider_description.provider_id != provider_id:
            setup_problems.append(
                _provision_problem(
                    "instrument_provider_id_mismatch",
                    "instrument provider description changed provider identity",
                    run_id=run_id,
                    operation_id=command.operation_id,
                )
            )
        advertised = {
            description.instrument_id: description
            for description in provider_description.instruments
            if description.instrument_id in instrument_claims
        }
        missing = tuple(
            instrument_id
            for instrument_id in instrument_ids
            if instrument_id not in advertised
        )
        setup_problems.extend(
            _provision_problem(
                "instrument_claim_not_described",
                f"instrument provider does not describe admitted claim {instrument_id}",
                run_id=run_id,
                operation_id=command.operation_id,
                instrument_id=instrument_id,
            )
            for instrument_id in missing
        )
        if setup_problems:
            return self._reject_run_provision(
                run_id,
                command,
                problems=tuple(setup_problems),
            )

        try:
            runtime, metadata = _provide_drivers(
                provider,
                config=config,
                instrument_ids=instrument_ids,
                expected=advertised,
            )
        except _ProvisioningRejected as error:
            if _call_all(error.drivers, _close_driver):
                self._mark_run_unknown(
                    run_id,
                    token=command.lease_id,
                    reason="run_instrument_provisioning_cleanup_failed",
                )
                raise BackendConflict(
                    "instrument provisioning rejection could not be released"
                ) from error
            return self._reject_run_provision(
                run_id,
                command,
                problems=error.problems,
            )
        except _ProvisioningUnknown as error:
            _call_all(error.drivers, _abort_driver)
            _call_all(error.drivers, _close_driver)
            self._mark_run_unknown(
                run_id,
                token=command.lease_id,
                reason="run_instrument_provisioning_unknown",
            )
            raise BackendConflict(
                "instrument provider failed while connecting"
            ) from error

        try:
            self._record_run_operation_event(
                run_id,
                token=command.lease_id,
                instrument_id=None,
                operation_id=command.operation_id,
                event_kind="run_instruments_provisioned",
                status="ready",
            )
        except BackendConflict:
            _call_all(runtime.drivers.values(), _abort_driver)
            _call_all(runtime.drivers.values(), _close_driver)
            self._mark_run_unknown(
                run_id,
                token=command.lease_id,
                reason="run_instrument_provisioning_fence_lost",
            )
            raise

        receipt = RunInstrumentProvisionReceipt(
            run_id=run_id,
            operation_id=command.operation_id,
            status="ready",
            provider_id=provider_id,
            instrument_ids=instrument_ids,
            descriptions=tuple(runtime.descriptions[item] for item in instrument_ids),
            metadata=metadata,
        )
        provision = _RunProvision(
            command=command,
            receipt=receipt,
            lock=self._run_operation_lock(run_id),
        )
        runtime.ledger = provision.ledger
        self._store_run_provision(run_id, provision, runtime=runtime)
        return receipt

    def _reject_run_provision(
        self,
        run_id: str,
        command: RunInstrumentProvisionCommand,
        *,
        problems: tuple[Problem, ...],
    ) -> RunInstrumentProvisionReceipt:
        receipt = RunInstrumentProvisionReceipt(
            run_id=run_id,
            operation_id=command.operation_id,
            status="rejected",
            problems=problems,
        )
        self._store_run_provision(
            run_id,
            _RunProvision(
                command=command,
                receipt=receipt,
                lock=self._run_operation_lock(run_id),
            ),
        )
        return receipt

    def read_run_state(
        self,
        run_id: str,
        instrument_id: str,
        command: RunInstrumentReadCommand,
    ) -> InstrumentStateSnapshot:
        with self._run_operation_lock(run_id):
            provision, cached = self._begin_run_operation(
                run_id,
                instrument_id=instrument_id,
                kind="read",
                command=command,
            )
            if cached is not None:
                if not isinstance(cached.result, InstrumentStateSnapshot):
                    raise BackendConflict("run instrument read did not complete")
                return cached.result
            runtime, driver = self._run_driver(run_id, instrument_id)
            with runtime.lock:
                try:
                    self._record_run_operation_event(
                        run_id,
                        token=command.lease_id,
                        instrument_id=instrument_id,
                        operation_id=command.operation_id,
                        event_kind="run_instrument_read_started",
                        status=None,
                    )
                    state = _read_driver_state(
                        driver,
                        instrument_id=instrument_id,
                    )
                    self._record_run_operation_event(
                        run_id,
                        token=command.lease_id,
                        instrument_id=instrument_id,
                        operation_id=command.operation_id,
                        event_kind="run_instrument_read_finished",
                        status="read",
                    )
                except BackendConflict as error:
                    self._fail_run_operation(
                        provision,
                        command.operation_id,
                        message=str(error),
                    )
                    raise
                self._complete_run_operation(
                    provision,
                    command.operation_id,
                    result=state,
                )
                return state

    def apply_run_state(
        self,
        run_id: str,
        instrument_id: str,
        request: RunInstrumentApplyCommand,
    ) -> ApplyReceipt:
        if request.command.instrument_id != instrument_id:
            raise BackendConflict("instrument apply command does not match its route")
        with self._run_operation_lock(run_id):
            provision, cached = self._begin_run_operation(
                run_id,
                instrument_id=instrument_id,
                kind="apply",
                command=request,
            )
            if cached is not None:
                if not isinstance(cached.result, ApplyReceipt):
                    raise BackendConflict("run instrument apply did not complete")
                return cached.result
            runtime, driver = self._run_driver(run_id, instrument_id)
            with runtime.lock:
                try:
                    receipt = self._apply_live(
                        runtime,
                        driver,
                        command=request.command,
                        conflict_scope="run",
                        on_started=lambda: self._record_run_operation_event(
                            run_id,
                            token=request.lease_id,
                            instrument_id=instrument_id,
                            operation_id=request.operation_id,
                            event_kind="run_instrument_apply_started",
                            status=None,
                        ),
                        on_finished=lambda status: self._record_run_operation_event(
                            run_id,
                            token=request.lease_id,
                            instrument_id=instrument_id,
                            operation_id=request.operation_id,
                            event_kind="run_instrument_apply_finished",
                            status=status,
                        ),
                        on_unknown=lambda reason: self._lose_run_runtime(
                            run_id,
                            runtime,
                            token=request.lease_id,
                            reason=f"run_{reason}",
                        ),
                    )
                except BackendConflict as error:
                    self._fail_run_operation(
                        provision,
                        request.operation_id,
                        message=str(error),
                    )
                    raise
                self._complete_run_operation(
                    provision,
                    request.operation_id,
                    result=receipt,
                )
                return receipt

    def collect_run(
        self,
        run_id: str,
        instrument_id: str,
        request: RunInstrumentCollectCommand,
    ) -> CollectReceipt:
        if request.command.instrument_id != instrument_id:
            raise BackendConflict("instrument collect command does not match its route")
        with self._run_operation_lock(run_id):
            provision, cached = self._begin_run_operation(
                run_id,
                instrument_id=instrument_id,
                kind="collect",
                command=request,
            )
            if cached is not None:
                if not isinstance(cached.result, CollectReceipt):
                    raise BackendConflict("run instrument collect did not complete")
                return cached.result
            runtime, driver = self._run_driver(run_id, instrument_id)
            with runtime.lock:
                try:
                    receipt = self._collect_live(
                        runtime,
                        driver,
                        command=request.command,
                        conflict_scope="run",
                        on_started=lambda: self._record_run_operation_event(
                            run_id,
                            token=request.lease_id,
                            instrument_id=instrument_id,
                            operation_id=request.operation_id,
                            event_kind="run_instrument_collect_started",
                            status=None,
                        ),
                        on_finished=lambda status: self._record_run_operation_event(
                            run_id,
                            token=request.lease_id,
                            instrument_id=instrument_id,
                            operation_id=request.operation_id,
                            event_kind="run_instrument_collect_finished",
                            status=status,
                        ),
                        on_unknown=lambda reason: self._lose_run_runtime(
                            run_id,
                            runtime,
                            token=request.lease_id,
                            reason=f"run_{reason}",
                        ),
                    )
                except BackendConflict as error:
                    self._fail_run_operation(
                        provision,
                        request.operation_id,
                        message=str(error),
                    )
                    raise
                self._complete_run_operation(
                    provision,
                    request.operation_id,
                    result=receipt,
                )
                return receipt

    def run_lifecycle(
        self,
        run_id: str,
        instrument_id: str,
        command: RunInstrumentLifecycleCommand,
    ) -> RunInstrumentLifecycleReceipt:
        with self._run_operation_lock(run_id):
            provision, cached = self._begin_run_operation(
                run_id,
                instrument_id=instrument_id,
                kind="lifecycle",
                command=command,
            )
            if cached is not None:
                if not isinstance(cached.result, RunInstrumentLifecycleReceipt):
                    raise BackendConflict("run instrument lifecycle did not complete")
                return cached.result
            runtime, driver = self._run_driver(run_id, instrument_id)
            with runtime.lock:
                try:
                    self._record_run_operation_event(
                        run_id,
                        token=command.lease_id,
                        instrument_id=instrument_id,
                        operation_id=command.operation_id,
                        event_kind=f"run_instrument_{command.action}_started",
                        status=None,
                    )
                    try:
                        _run_driver_lifecycle(driver, command.action)
                    except Exception as error:
                        self._lose_run_runtime(
                            run_id,
                            runtime,
                            token=command.lease_id,
                            reason=f"run_instrument_{command.action}_unknown",
                            skip_abort=(
                                frozenset({instrument_id})
                                if command.action == "abort"
                                else frozenset()
                            ),
                            skip_close=(
                                frozenset({instrument_id})
                                if command.action == "close"
                                else frozenset()
                            ),
                        )
                        raise BackendConflict(
                            f"instrument {command.action} failed with unknown state"
                        ) from error
                    if command.action == "close":
                        runtime.drivers.pop(instrument_id)
                    receipt = RunInstrumentLifecycleReceipt(
                        run_id=run_id,
                        instrument_id=instrument_id,
                        operation_id=command.operation_id,
                        action=command.action,
                    )
                    try:
                        self._record_run_operation_event(
                            run_id,
                            token=command.lease_id,
                            instrument_id=instrument_id,
                            operation_id=command.operation_id,
                            event_kind=f"run_instrument_{command.action}_finished",
                            status="completed",
                        )
                    except BackendConflict:
                        self._lose_run_runtime(
                            run_id,
                            runtime,
                            token=command.lease_id,
                            reason=(f"run_instrument_{command.action}_audit_unknown"),
                            skip_abort=(
                                frozenset({instrument_id})
                                if command.action == "abort"
                                else frozenset()
                            ),
                        )
                        raise
                except BackendConflict as error:
                    self._fail_run_operation(
                        provision,
                        command.operation_id,
                        message=str(error),
                    )
                    raise
                self._complete_run_operation(
                    provision,
                    command.operation_id,
                    result=receipt,
                )
                if command.action == "close" and not runtime.drivers:
                    self._pop_run_runtime(run_id, expected=runtime)
                return receipt

    def _begin_run_operation(
        self,
        run_id: str,
        *,
        instrument_id: str,
        kind: Literal["read", "apply", "collect", "lifecycle"],
        command: (
            RunInstrumentReadCommand
            | RunInstrumentApplyCommand
            | RunInstrumentCollectCommand
            | RunInstrumentLifecycleCommand
        ),
    ) -> tuple[_RunProvision, _RunOperation | None]:
        self._fence_run(run_id, command.lease_id)
        if self._run_is_finalizing(run_id):
            raise BackendConflict("run instrument host is finalizing")
        provision = self._run_provision_state(run_id)
        if provision is None:
            raise BackendConflict("run instruments have not been provisioned")
        if provision.receipt.status != "ready":
            raise BackendConflict("run instrument provisioning was rejected")
        if provision.command.operation_id == command.operation_id:
            raise BackendConflict(
                "run operation id was already used for instrument provisioning"
            )
        cached = provision.ledger.run_operations.get(command.operation_id)
        if cached is not None:
            if (
                cached.kind != kind
                or cached.instrument_id != instrument_id
                or cached.command != command
            ):
                raise BackendConflict(
                    "run operation id has different instrument operation content"
                )
            if cached.failure is not None:
                raise BackendConflict(cached.failure)
            return provision, cached
        self._run_driver(run_id, instrument_id)
        provision.ledger.run_operations[command.operation_id] = _RunOperation(
            kind=kind,
            instrument_id=instrument_id,
            command=command,
            result=None,
        )
        return provision, None

    @staticmethod
    def _complete_run_operation(
        provision: _RunProvision,
        operation_id: str,
        *,
        result: (
            InstrumentStateSnapshot
            | ApplyReceipt
            | CollectReceipt
            | RunInstrumentLifecycleReceipt
        ),
    ) -> None:
        pending = provision.ledger.run_operations[operation_id]
        provision.ledger.run_operations[operation_id] = _RunOperation(
            kind=pending.kind,
            instrument_id=pending.instrument_id,
            command=pending.command,
            result=result,
        )

    @staticmethod
    def _fail_run_operation(
        provision: _RunProvision,
        operation_id: str,
        *,
        message: str,
    ) -> None:
        pending = provision.ledger.run_operations[operation_id]
        provision.ledger.run_operations[operation_id] = _RunOperation(
            kind=pending.kind,
            instrument_id=pending.instrument_id,
            command=pending.command,
            result=None,
            failure=message,
        )

    def _run_operation_lock(self, run_id: str) -> RLock:
        with self._run_lock:
            provision = self._run_provisions.get(run_id)
            if provision is not None:
                return provision.lock
            return self._run_open_locks.setdefault(run_id, RLock())

    def _run_provision_state(self, run_id: str) -> _RunProvision | None:
        with self._run_lock:
            return self._run_provisions.get(run_id)

    def _run_is_finalizing(self, run_id: str) -> bool:
        with self._run_lock:
            return run_id in self._finalizing_runs

    def _run_runtime_state(self, run_id: str) -> _LiveDrivers | None:
        with self._run_lock:
            return self._run_runtimes.get(run_id)

    def _store_run_provision(
        self,
        run_id: str,
        provision: _RunProvision,
        *,
        runtime: _LiveDrivers | None = None,
    ) -> None:
        with self._run_lock:
            self._run_provisions[run_id] = provision
            if runtime is not None:
                self._run_runtimes[run_id] = runtime
            self._run_open_locks.pop(run_id, None)

    def _pop_run_runtime(
        self,
        run_id: str,
        *,
        expected: _LiveDrivers | None = None,
    ) -> _LiveDrivers | None:
        with self._run_lock:
            runtime = self._run_runtimes.get(run_id)
            if expected is not None and runtime is not expected:
                return None
            return self._run_runtimes.pop(run_id, None)

    def _run_driver(
        self,
        run_id: str,
        instrument_id: str,
    ) -> tuple[_LiveDrivers, InstrumentDriver]:
        runtime = self._run_runtime_state(run_id)
        if runtime is None:
            raise BackendConflict("run has no live daemon instrument drivers")
        try:
            return runtime, runtime.drivers[instrument_id]
        except KeyError as error:
            raise BackendNotFound(
                f"instrument is not live for run {run_id}: {instrument_id}"
            ) from error

    def open_session(
        self,
        command: InstrumentSessionOpenCommand,
    ) -> InstrumentSessionLease:
        with self._open_lock:
            return self._open_session(command)

    def _open_session(
        self,
        command: InstrumentSessionOpenCommand,
    ) -> InstrumentSessionLease:
        active = self._config.get_active_config()
        configured = {
            spec.id: spec for spec in active.config.instrument_registry.instruments
        }
        missing = tuple(
            instrument_id
            for instrument_id in command.instrument_ids
            if instrument_id not in configured
        )
        if missing:
            raise BackendNotFound(f"instrument was not found: {', '.join(missing)}")
        provider = self._provider(active.config)
        descriptions = self._selected_descriptions(
            provider,
            config=active.config,
            instrument_ids=command.instrument_ids,
        )
        try:
            session = self._control.open_instrument_session(
                operation_id=command.operation_id,
                actor=command.actor,
                config_entry_id=active.entry.id,
                config_content_hash=active.entry.content_hash,
                instrument_ids=command.instrument_ids,
                ttl=self._lease_ttl,
            )
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error
        with self._sessions_lock:
            existing_runtime = self._sessions.get(session.session_id)
        if existing_runtime is not None:
            return self._wire_lease(session, existing_runtime)

        try:
            runtime, _metadata = _provide_drivers(
                provider,
                config=active.config,
                instrument_ids=command.instrument_ids,
                expected=descriptions,
            )
        except _ProvisioningRejected as error:
            close_failed = _call_all(error.drivers, _close_driver)
            if close_failed:
                self._mark_unknown(
                    session,
                    reason="instrument_provisioning_cleanup_failed",
                )
            else:
                with self._attention_lock:
                    try:
                        self._control.close_instrument_session(
                            session.session_id,
                            token=_session_token(session),
                        )
                    except InstrumentSessionLeaseNotHeld as lease_error:
                        self.expire_sessions()
                        raise BackendConflict(
                            "instrument session lease expired while connecting"
                        ) from lease_error
            raise BackendConflict(str(error)) from error
        except _ProvisioningUnknown as error:
            _call_all(error.drivers, _abort_driver)
            _call_all(error.drivers, _close_driver)
            self._mark_unknown(session, reason="instrument_provisioning_unknown")
            raise BackendConflict(
                "instrument provider failed while connecting"
            ) from error

        with self._attention_lock:
            try:
                session = self._control.renew_instrument_session(
                    session.session_id,
                    _session_token(session),
                    ttl=self._lease_ttl,
                )
            except InstrumentSessionLeaseNotHeld as error:
                _call_all(runtime.drivers.values(), _abort_driver)
                _call_all(runtime.drivers.values(), _close_driver)
                raise BackendConflict(
                    "instrument session lease expired while connecting"
                ) from error
            with self._sessions_lock:
                self._sessions[session.session_id] = runtime
        return self._wire_lease(session, runtime)

    def heartbeat(
        self,
        session_id: str,
        heartbeat: InstrumentSessionHeartbeat,
    ) -> InstrumentSessionLease:
        try:
            renewed = self._control.renew_instrument_session(
                session_id,
                heartbeat.lease_id,
                ttl=self._lease_ttl,
            )
            runtime = self._live_runtime(session_id)
        except (
            ControlPlaneConflict,
            InstrumentSessionLeaseNotHeld,
        ) as error:
            raise BackendConflict(
                "instrument session lease is absent, stale, or expired"
            ) from error
        return self._wire_lease(renewed, runtime)

    def read_state(
        self,
        session_id: str,
        instrument_id: str,
        command: InstrumentSessionReadCommand,
    ) -> InstrumentStateSnapshot:
        runtime = self._live_runtime(session_id)
        with runtime.lock:
            _session, _runtime, driver = self._fenced_driver(
                session_id,
                instrument_id,
                command.lease_id,
            )
            return _read_driver_state(driver, instrument_id=instrument_id)

    def apply_state(
        self,
        session_id: str,
        instrument_id: str,
        request: InstrumentSessionApplyCommand,
    ) -> ApplyReceipt:
        if request.command.instrument_id != instrument_id:
            raise BackendConflict("instrument apply command does not match its route")
        runtime = self._live_runtime(session_id)
        with runtime.lock:
            session, _runtime, driver = self._fenced_driver(
                session_id,
                instrument_id,
                request.lease_id,
            )
            operation_id = request.command.operation_id
            assert operation_id is not None
            return self._apply_live(
                runtime,
                driver,
                command=request.command,
                conflict_scope="interactive",
                on_started=lambda: self._record_operation_started(
                    session,
                    instrument_id=instrument_id,
                    operation_id=operation_id,
                    kind="apply",
                ),
                on_finished=lambda status: self._record_operation_finished(
                    session,
                    instrument_id=instrument_id,
                    operation_id=operation_id,
                    kind="apply",
                    status=status,
                ),
                on_unknown=lambda reason: self._lose_runtime(
                    session,
                    runtime,
                    reason=reason,
                ),
            )

    def collect(
        self,
        session_id: str,
        instrument_id: str,
        request: InstrumentSessionCollectCommand,
    ) -> CollectReceipt:
        if request.command.instrument_id != instrument_id:
            raise BackendConflict("instrument collect command does not match its route")
        if request.command.point_index != 0 or request.command.point_count != 1:
            raise BackendConflict("interactive collect uses exactly one implicit point")
        runtime = self._live_runtime(session_id)
        with runtime.lock:
            session, _runtime, driver = self._fenced_driver(
                session_id,
                instrument_id,
                request.lease_id,
            )
            operation_id = request.command.operation_id
            assert operation_id is not None
            return self._collect_live(
                runtime,
                driver,
                command=request.command,
                conflict_scope="interactive",
                on_started=lambda: self._record_operation_started(
                    session,
                    instrument_id=instrument_id,
                    operation_id=operation_id,
                    kind="collect",
                ),
                on_finished=lambda status: self._record_operation_finished(
                    session,
                    instrument_id=instrument_id,
                    operation_id=operation_id,
                    kind="collect",
                    status=status,
                ),
                on_unknown=lambda reason: self._lose_runtime(
                    session,
                    runtime,
                    reason=reason,
                ),
            )

    def _apply_live(
        self,
        runtime: _LiveDrivers,
        driver: InstrumentDriver,
        *,
        command: InstrumentStateCommand,
        conflict_scope: str,
        on_started: Callable[[], None],
        on_finished: Callable[[str], None],
        on_unknown: Callable[[str], None],
    ) -> ApplyReceipt:
        validation_problems = validate_state_command(
            command=command,
            description=runtime.descriptions[command.instrument_id],
        )
        if validation_problems:
            raise BackendConflict(
                "; ".join(item.message for item in validation_problems)
            )
        operation_id = command.operation_id
        assert operation_id is not None
        cached = runtime.apply_receipts.get(operation_id)
        if cached is not None:
            cached_command, cached_receipt = cached
            if cached_command != command:
                raise BackendConflict(
                    f"{conflict_scope} operation id has different apply content"
                )
            return cached_receipt
        if (
            operation_id in runtime.collect_receipts
            or operation_id in runtime.collect_failures
        ):
            raise BackendConflict(
                f"{conflict_scope} operation id was already used for collect"
            )
        on_started()
        try:
            receipt = driver.apply_state(command)
        except Exception as error:
            on_unknown("instrument_apply_unknown")
            raise BackendConflict(
                "instrument apply failed with unknown state"
            ) from error
        runtime.apply_receipts[operation_id] = (command, receipt)
        try:
            on_finished(receipt.status)
        except Exception as error:
            on_unknown("instrument_apply_audit_unknown")
            raise BackendConflict(
                "instrument apply completed but audit recording failed"
            ) from error
        if receipt.status == "unknown":
            on_unknown("instrument_apply_receipt_unknown")
        return receipt

    def _collect_live(
        self,
        runtime: _LiveDrivers,
        driver: InstrumentDriver,
        *,
        command: CollectCommand,
        conflict_scope: str,
        on_started: Callable[[], None],
        on_finished: Callable[[str], None],
        on_unknown: Callable[[str], None],
    ) -> CollectReceipt:
        validation_problems = validate_collect_command(
            command=command,
            description=runtime.descriptions[command.instrument_id],
        )
        if validation_problems:
            raise BackendConflict(
                "; ".join(item.message for item in validation_problems)
            )
        operation_id = command.operation_id
        assert operation_id is not None
        cached = runtime.collect_receipts.get(operation_id)
        if cached is not None:
            cached_command, cached_receipt = cached
            if cached_command != command:
                raise BackendConflict(
                    f"{conflict_scope} operation id has different collect content"
                )
            return cached_receipt
        cached_failure = runtime.collect_failures.get(operation_id)
        if cached_failure is not None:
            cached_command, cached_message = cached_failure
            if cached_command != command:
                raise BackendConflict(
                    f"{conflict_scope} operation id has different collect content"
                )
            raise BackendConflict(cached_message)
        if operation_id in runtime.apply_receipts:
            raise BackendConflict(
                f"{conflict_scope} operation id was already used for apply"
            )
        on_started()
        try:
            receipt = driver.collect(command)
        except Exception as error:
            on_unknown("instrument_collect_unknown")
            raise BackendConflict(
                "instrument collect failed with unknown state"
            ) from error
        receipt_problems = validate_collect_receipt(
            command=command,
            receipt=receipt,
        )
        if receipt_problems:
            message = "; ".join(item.message for item in receipt_problems)
            try:
                on_finished("invalid_receipt")
            except Exception as error:
                on_unknown("instrument_collect_audit_unknown")
                raise BackendConflict(
                    "instrument collect completed but audit recording failed"
                ) from error
            runtime.collect_failures[operation_id] = (command, message)
            raise BackendConflict(message)
        runtime.collect_receipts[operation_id] = (command, receipt)
        try:
            on_finished(receipt.status)
        except Exception as error:
            on_unknown("instrument_collect_audit_unknown")
            raise BackendConflict(
                "instrument collect completed but audit recording failed"
            ) from error
        if receipt.status == "unknown":
            on_unknown("instrument_collect_receipt_unknown")
        return receipt

    def close_session(
        self,
        session_id: str,
        command: InstrumentSessionEndCommand,
    ) -> InstrumentSessionEndReceipt:
        return self._end_session(
            session_id,
            command,
            abort=False,
        )

    def abort_session(
        self,
        session_id: str,
        command: InstrumentSessionEndCommand,
    ) -> InstrumentSessionEndReceipt:
        return self._end_session(
            session_id,
            command,
            abort=True,
        )

    def resolve_attention(self, session_id: str) -> InstrumentSessionEndReceipt:
        with self._open_lock, self._attention_lock:
            try:
                session = self._control.get_instrument_session(session_id)
                if session.state == "attention_required":
                    self._cleanup_session_runtime(session_id)
                _session, released = self._control.resolve_instrument_session_attention(
                    session_id
                )
            except ControlPlaneNotFound as error:
                raise BackendNotFound(str(error)) from error
            except ControlPlaneConflict as error:
                raise BackendConflict(str(error)) from error
        return InstrumentSessionEndReceipt(
            session_id=session_id,
            operation_id="operator-attention-resolution",
            status="aborted",
            released_resource_count=released,
        )

    def expire_sessions(self) -> None:
        expired = self._control.expire_instrument_sessions()
        for session_id in expired:
            self._cleanup_session_runtime(session_id)

    def _cleanup_session_runtime(self, session_id: str) -> None:
        with self._sessions_lock:
            runtime = self._sessions.get(session_id)
        if runtime is None:
            return
        with runtime.lock:
            with self._sessions_lock:
                if self._sessions.get(session_id) is not runtime:
                    return
            _call_all(runtime.drivers.values(), _abort_driver)
            _call_all(runtime.drivers.values(), _close_driver)
            with self._sessions_lock:
                if self._sessions.get(session_id) is runtime:
                    self._sessions.pop(session_id)

    def expire_leases(self) -> None:
        """Fence expired owners and finish cleanup before attention can resolve."""

        with self._attention_lock:
            self.expire_runs(self._control.expire_executor_leases())
            self.expire_sessions()

    def finalize_run(self, run_id: str, *, token: str) -> None:
        """Release any drivers left behind before committing a terminal run."""

        with self._run_operation_lock(run_id):
            self._fence_run(run_id, token)
            with self._run_lock:
                self._finalizing_runs.add(run_id)
            runtime = self._pop_run_runtime(run_id)
            if runtime is None:
                return
            with runtime.lock:
                failed = _call_all(runtime.drivers.values(), _abort_driver)
                failed = _call_all(runtime.drivers.values(), _close_driver) or failed
            if failed:
                self._mark_run_unknown(
                    run_id,
                    token=token,
                    reason="run_instrument_finalization_unknown",
                )
                raise BackendConflict(
                    "run instrument connections could not be released"
                )

    def release_run(self, run_id: str) -> None:
        """Drop volatile idempotency state after the run is durably closed."""

        self._discard_run_state(run_id)

    def _discard_run_state(self, run_id: str) -> None:
        with self._run_lock:
            self._run_runtimes.pop(run_id, None)
            self._run_provisions.pop(run_id, None)
            self._run_open_locks.pop(run_id, None)
            self._finalizing_runs.discard(run_id)

    def expire_runs(self, run_ids: Iterable[str]) -> None:
        """Release in-memory drivers after their executor leases were fenced."""

        for run_id in run_ids:
            self._cleanup_run_state(run_id)

    def await_run_cleanup(self, run_id: str) -> None:
        """Complete hardware cleanup before quarantined resources are released."""

        try:
            run = self._control.get_run(run_id)
        except ControlPlaneNotFound:
            return
        if run.state == "attention_required":
            self._cleanup_run_state(run_id)

    def resolve_run_attention[T](
        self,
        run_id: str,
        resolver: Callable[[str], T],
    ) -> T:
        with self._attention_lock:
            self.await_run_cleanup(run_id)
            return resolver(run_id)

    def _cleanup_run_state(self, run_id: str) -> None:
        lock = self._run_operation_lock(run_id)
        with lock:
            with self._run_lock:
                self._run_open_locks[run_id] = lock
                runtime = self._run_runtimes.pop(run_id, None)
                self._run_provisions.pop(run_id, None)
                self._finalizing_runs.discard(run_id)
            if runtime is not None:
                with runtime.lock:
                    _call_all(runtime.drivers.values(), _abort_driver)
                    _call_all(runtime.drivers.values(), _close_driver)
            with self._run_lock:
                if self._run_open_locks.get(run_id) is lock:
                    self._run_open_locks.pop(run_id)

    def reconcile_startup(self) -> None:
        with self._attention_lock:
            self.expire_runs(self._control.abandon_executor_leases())
            abandoned_sessions = self._control.abandon_instrument_sessions()
            for session_id in abandoned_sessions:
                self._cleanup_session_runtime(session_id)

    def shutdown(self) -> None:
        with self._sessions_lock:
            sessions = tuple(self._sessions.items())
            self._sessions.clear()
        for session_id, runtime in sessions:
            try:
                session = self._control.get_instrument_session(session_id)
            except ControlPlaneNotFound:
                session = None
            with runtime.lock:
                _call_all(runtime.drivers.values(), _abort_driver)
                _call_all(runtime.drivers.values(), _close_driver)
            if session is not None and session.state == "active":
                self._mark_unknown(session, reason="daemon_shutting_down")
        with self._run_lock:
            run_provisions = tuple(self._run_provisions.items())
            run_runtimes = self._run_runtimes
            self._run_provisions = {}
            self._run_runtimes = {}
            self._run_open_locks = {}
            self._finalizing_runs = set()
        for run_id, provision in run_provisions:
            runtime = run_runtimes.get(run_id)
            if runtime is not None:
                with runtime.lock:
                    _call_all(runtime.drivers.values(), _abort_driver)
                    _call_all(runtime.drivers.values(), _close_driver)
            self._mark_run_unknown(
                run_id,
                token=provision.command.lease_id,
                reason="daemon_shutting_down",
            )
        with self._provider_lock:
            self._provider_content_hash = None
            self._cached_provider = None

    def _end_session(
        self,
        session_id: str,
        command: InstrumentSessionEndCommand,
        *,
        abort: bool,
    ) -> InstrumentSessionEndReceipt:
        cached = self._ended_session_receipt(
            session_id,
            command,
            abort=abort,
        )
        if cached is not None:
            return cached
        try:
            session = self._control.validate_instrument_session(
                session_id,
                token=command.lease_id,
            )
            runtime = self._live_runtime(session_id)
        except (
            ControlPlaneConflict,
            InstrumentSessionLeaseNotHeld,
        ) as error:
            raise BackendConflict(
                "instrument session lease is absent, stale, or expired"
            ) from error
        with runtime.lock:
            cached = self._ended_session_receipt(
                session_id,
                command,
                abort=abort,
            )
            if cached is not None:
                return cached
            try:
                session = self._control.validate_instrument_session(
                    session_id,
                    token=command.lease_id,
                )
            except InstrumentSessionLeaseNotHeld as error:
                raise BackendConflict(
                    "instrument session lease is absent, stale, or expired"
                ) from error
            failed = (
                _call_all(runtime.drivers.values(), _abort_driver) if abort else False
            )
            failed = _call_all(runtime.drivers.values(), _close_driver) or failed
            if failed:
                self._lose_runtime(
                    session,
                    runtime,
                    reason=(
                        "instrument_abort_unknown"
                        if abort
                        else "instrument_close_unknown"
                    ),
                )
                raise BackendConflict("instrument connection release was not confirmed")
            try:
                _closed, released = self._control.close_instrument_session(
                    session_id,
                    token=command.lease_id,
                )
            except ControlPlaneConflict as error:
                raise BackendConflict(str(error)) from error
            receipt = InstrumentSessionEndReceipt(
                session_id=session_id,
                operation_id=command.operation_id,
                status="aborted" if abort else "closed",
                released_resource_count=released,
            )
            with self._sessions_lock:
                self._sessions.pop(session_id, None)
                self._ended_sessions[session_id] = _EndedSession(
                    command=command,
                    abort=abort,
                    receipt=receipt,
                )
                while len(self._ended_sessions) > self._ended_session_limit:
                    self._ended_sessions.popitem(last=False)
            return receipt

    def _ended_session_receipt(
        self,
        session_id: str,
        command: InstrumentSessionEndCommand,
        *,
        abort: bool,
    ) -> InstrumentSessionEndReceipt | None:
        with self._sessions_lock:
            ended = self._ended_sessions.get(session_id)
        if ended is None:
            return None
        if ended.command.operation_id != command.operation_id:
            raise BackendConflict("instrument session is already ended")
        if ended.command != command or ended.abort != abort:
            raise BackendConflict(
                "instrument session end operation id has different content"
            )
        return ended.receipt

    def _fenced_driver(
        self,
        session_id: str,
        instrument_id: str,
        token: str,
    ) -> tuple[InstrumentSession, _LiveDrivers, InstrumentDriver]:
        try:
            session = self._control.validate_instrument_session(
                session_id,
                token=token,
            )
            runtime = self._live_runtime(session_id)
        except (
            ControlPlaneConflict,
            InstrumentSessionLeaseNotHeld,
        ) as error:
            raise BackendConflict(
                "instrument session lease is absent, stale, or expired"
            ) from error
        try:
            driver = runtime.drivers[instrument_id]
        except KeyError as error:
            raise BackendNotFound(
                f"instrument is not in session {session_id}: {instrument_id}"
            ) from error
        return session, runtime, driver

    def _live_runtime(self, session_id: str) -> _LiveDrivers:
        with self._sessions_lock:
            runtime = self._sessions.get(session_id)
        if runtime is None:
            raise BackendConflict("instrument session has no live daemon drivers")
        return runtime

    def _pop_runtime(self, session_id: str) -> _LiveDrivers | None:
        with self._sessions_lock:
            return self._sessions.pop(session_id, None)

    def _lose_runtime(
        self,
        session: InstrumentSession,
        runtime: _LiveDrivers,
        *,
        reason: str,
    ) -> None:
        _call_all(runtime.drivers.values(), _abort_driver)
        _call_all(runtime.drivers.values(), _close_driver)
        self._pop_runtime(session.session_id)
        self._mark_unknown(session, reason=reason)

    def _lose_run_runtime(
        self,
        run_id: str,
        runtime: _LiveDrivers,
        *,
        token: str,
        reason: str,
        skip_abort: frozenset[str] | None = None,
        skip_close: frozenset[str] | None = None,
    ) -> None:
        drivers = tuple(runtime.drivers.values())
        skipped_aborts = skip_abort or frozenset()
        skipped_closes = skip_close or frozenset()
        _call_all(
            (
                driver
                for driver in drivers
                if driver.instrument_id not in skipped_aborts
            ),
            _abort_driver,
        )
        _call_all(
            (
                driver
                for driver in drivers
                if driver.instrument_id not in skipped_closes
            ),
            _close_driver,
        )
        self._pop_run_runtime(run_id, expected=runtime)
        self._mark_run_unknown(
            run_id,
            token=token,
            reason=reason,
        )

    def _mark_unknown(
        self,
        session: InstrumentSession,
        *,
        reason: str,
    ) -> None:
        with suppress(InstrumentSessionLeaseNotHeld):
            self._control.mark_instrument_session_unknown(
                session.session_id,
                token=_session_token(session),
                reason=reason,
            )

    def _record_operation_started(
        self,
        session: InstrumentSession,
        *,
        instrument_id: str,
        operation_id: str,
        kind: Literal["apply", "collect"],
    ) -> None:
        self._record_operation_event(
            session,
            instrument_id=instrument_id,
            operation_id=operation_id,
            event_kind=f"instrument_{kind}_started",
            status=None,
        )

    def _record_operation_finished(
        self,
        session: InstrumentSession,
        *,
        instrument_id: str,
        operation_id: str,
        kind: Literal["apply", "collect"],
        status: str,
    ) -> None:
        self._record_operation_event(
            session,
            instrument_id=instrument_id,
            operation_id=operation_id,
            event_kind=f"instrument_{kind}_finished",
            status=status,
        )

    def _record_operation_event(
        self,
        session: InstrumentSession,
        *,
        instrument_id: str,
        operation_id: str,
        event_kind: str,
        status: str | None,
    ) -> None:
        payload: dict[str, JsonValue] = {
            "session_id": session.session_id,
            "instrument_id": instrument_id,
            "operation_id": operation_id,
            "actor": session.actor,
        }
        if status is not None:
            payload["status"] = status
        try:
            with self._control.transaction() as connection:
                self._control.append_event_in_transaction(
                    connection,
                    DurableEventInput(
                        kind=event_kind,
                        payload=payload,
                    ),
                )
        except Exception as error:
            raise BackendConflict(
                "instrument operation audit event could not be recorded"
            ) from error

    def _fence_run(self, run_id: str, token: str) -> None:
        try:
            self._control.validate_executor_lease(run_id, token=token)
        except ExecutorLeaseNotHeld as error:
            raise BackendConflict(
                "executor lease is absent, stale, or expired"
            ) from error

    def _mark_run_unknown(
        self,
        run_id: str,
        *,
        token: str,
        reason: str,
    ) -> None:
        try:
            with suppress(ExecutorLeaseNotHeld):
                self._control.mark_executor_unknown(
                    run_id,
                    token=token,
                    reason=reason,
                )
        finally:
            self._discard_run_state(run_id)

    def _record_run_operation_event(
        self,
        run_id: str,
        *,
        token: str,
        instrument_id: str | None,
        operation_id: str,
        event_kind: str,
        status: str | None,
    ) -> None:
        payload: dict[str, JsonValue] = {"operation_id": operation_id}
        if instrument_id is not None:
            payload["instrument_id"] = instrument_id
        if status is not None:
            payload["status"] = status
        try:
            with self._control.fenced_transaction(
                run_id,
                token=token,
            ) as connection:
                self._control.append_event_in_transaction(
                    connection,
                    DurableEventInput(
                        run_id=run_id,
                        kind=event_kind,
                        payload=payload,
                    ),
                )
        except (ControlPlaneConflict, ExecutorLeaseNotHeld) as error:
            raise BackendConflict(
                "executor lease is absent, stale, or expired"
            ) from error
        except Exception as error:
            raise BackendConflict(
                "run instrument audit event could not be recorded"
            ) from error

    def _descriptions(
        self,
        config: ConfigProfileSnapshot,
    ) -> tuple[dict[str, InstrumentDescription], tuple[Problem, ...]]:
        if self._build_system is None:
            return {}, ()
        try:
            provider = self._provider(config)
            result = provider.describe(InstrumentProviderContext(config=config))
        except Exception:
            return {}, ()
        return (
            {
                description.instrument_id: description
                for description in result.instruments
            },
            result.problems,
        )

    def _selected_descriptions(
        self,
        provider: InstrumentProvider,
        *,
        config: ConfigProfileSnapshot,
        instrument_ids: tuple[str, ...],
    ) -> dict[str, InstrumentDescription]:
        try:
            result = provider.describe(
                InstrumentProviderContext(
                    config=config,
                    instrument_ids=instrument_ids,
                )
            )
        except Exception as error:
            raise BackendConflict("instrument provider description failed") from error
        if result.problems:
            raise BackendConflict("instrument provider cannot describe the session")
        descriptions = {
            description.instrument_id: description
            for description in result.instruments
            if description.instrument_id in instrument_ids
        }
        missing = tuple(
            instrument_id
            for instrument_id in instrument_ids
            if instrument_id not in descriptions
        )
        if missing:
            raise BackendConflict(
                f"instrument provider does not expose: {', '.join(missing)}"
            )
        return descriptions

    def _provider(self, config: ConfigProfileSnapshot) -> InstrumentProvider:
        if self._build_system is None:
            raise BackendConflict(
                "project application does not configure an instrument provider"
            )
        content_hash = config_content_hash(config)
        with self._provider_lock:
            if (
                self._provider_content_hash == content_hash
                and self._cached_provider is not None
            ):
                return self._cached_provider
            system = self._build_system(config)
            if system.provider is None:
                raise BackendConflict(
                    "project experiment system does not configure "
                    "an instrument provider"
                )
            self._provider_content_hash = content_hash
            self._cached_provider = system.provider
            return system.provider

    def _wire_lease(
        self,
        session: InstrumentSession,
        runtime: _LiveDrivers,
    ) -> InstrumentSessionLease:
        assert session.expires_at is not None
        return InstrumentSessionLease(
            session_id=session.session_id,
            lease_id=_session_token(session),
            actor=session.actor,
            config_entry_id=session.config_entry_id,
            config_content_hash=session.config_content_hash,
            instrument_ids=session.instrument_ids,
            descriptions=tuple(
                runtime.descriptions[instrument_id]
                for instrument_id in session.instrument_ids
            ),
            issued_at=session.renewed_at,
            expires_at=session.expires_at,
            heartbeat_interval_seconds=self._heartbeat_interval_seconds,
        )

    @staticmethod
    def _instrument_view(
        spec: InstrumentSpec,
        *,
        description: InstrumentDescription | None,
        lease: ResourceLease | None,
        owner_actor: str | None,
        problems: tuple[Problem, ...],
    ) -> InstrumentView:
        if lease is not None:
            availability = lease.status
        elif description is None:
            availability = "unavailable"
        else:
            availability = "available"
        return InstrumentView(
            spec=spec,
            description=description,
            availability=availability,
            owner_kind=None if lease is None else lease.owner_kind,
            owner_id=None if lease is None else lease.owner_id,
            owner_actor=owner_actor,
            expires_at=None if lease is None else lease.expires_at,
            problems=problems,
        )


class _ProvisioningRejected(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        problems: tuple[Problem, ...],
        drivers: tuple[InstrumentDriver, ...],
    ) -> None:
        self.problems = problems
        self.drivers = drivers
        super().__init__(message)


class _ProvisioningUnknown(RuntimeError):
    def __init__(self, drivers: tuple[InstrumentDriver, ...]) -> None:
        self.drivers = drivers
        super().__init__("instrument provisioning state is unknown")


def _provide_drivers(
    provider: InstrumentProvider,
    *,
    config: ConfigProfileSnapshot,
    instrument_ids: tuple[str, ...],
    expected: Mapping[str, InstrumentDescription],
) -> tuple[_LiveDrivers, dict[str, JsonValue]]:
    drivers: tuple[InstrumentDriver, ...] = ()
    try:
        result = provider.provide(
            InstrumentProviderContext(
                config=config,
                instrument_ids=instrument_ids,
            )
        )
        drivers = result.drivers
        if result.problems:
            raise _ProvisioningRejected(
                "instrument provider rejected provisioning",
                problems=result.problems,
                drivers=drivers,
            )
        problems = validate_instruments(
            config=config,
            instruments=list(drivers),
        )
        actual, description_problems = describe_instruments(list(drivers))
        problems.extend(description_problems)
        actual_by_id = {
            description.instrument_id: description for description in actual
        }
        if tuple(actual_by_id) != instrument_ids:
            problems.append(
                _provision_problem(
                    "instrument_provider_result_order_mismatch",
                    "instrument provider did not return requested drivers in order",
                )
            )
        for instrument_id in set(instrument_ids) & actual_by_id.keys():
            if actual_by_id[instrument_id] != expected[instrument_id]:
                problems.append(
                    _provision_problem(
                        "instrument_description_changed",
                        (
                            f"instrument description changed while provisioning "
                            f"{instrument_id}"
                        ),
                        instrument_id=instrument_id,
                    )
                )
        if problems:
            raise _ProvisioningRejected(
                "instrument provider returned invalid drivers",
                problems=tuple(problems),
                drivers=drivers,
            )
        return (
            _LiveDrivers(
                drivers={driver.instrument_id: driver for driver in drivers},
                descriptions=actual_by_id,
            ),
            result.metadata,
        )
    except _ProvisioningRejected:
        raise
    except Exception as error:
        raise _ProvisioningUnknown(drivers) from error


def _provision_problem(
    code: str,
    message: str,
    *,
    run_id: str | None = None,
    operation_id: str | None = None,
    instrument_id: str | None = None,
    details: Mapping[str, object] | None = None,
) -> Problem:
    location = (
        RuntimeLocation(
            run_id=run_id,
            operation_id=operation_id,
            instrument_id=instrument_id,
        )
        if run_id is not None or operation_id is not None
        else ModelLocation(
            root="instrument_provider",
            path=(() if instrument_id is None else ("instruments", instrument_id)),
        )
    )
    return problem(
        code,
        message,
        phase=ProblemPhase.PROVIDER_PREFLIGHT,
        location=location,
        details=details,
    )


def _session_token(session: InstrumentSession) -> str:
    if session.token is None:
        raise InstrumentSessionLeaseNotHeld("instrument session has no live token")
    return session.token


def _call_all(
    drivers: Iterable[InstrumentDriver],
    operation: Callable[[InstrumentDriver], None],
) -> bool:
    failed = False
    for driver in reversed(tuple(drivers)):
        try:
            operation(driver)
        except Exception:
            failed = True
    return failed


def _close_driver(driver: InstrumentDriver) -> None:
    driver.close()


def _abort_driver(driver: InstrumentDriver) -> None:
    driver.abort()


def _read_driver_state(
    driver: InstrumentDriver,
    *,
    instrument_id: str,
) -> InstrumentStateSnapshot:
    try:
        state = driver.read_state()
    except Exception as error:
        raise BackendConflict("instrument state read failed") from error
    if state.instrument_id != instrument_id:
        raise BackendConflict("instrument returned state for another instrument")
    return state


def _run_driver_lifecycle(
    driver: InstrumentDriver,
    action: Literal["cleanup", "abort", "close"],
) -> None:
    if action == "cleanup":
        driver.cleanup()
    elif action == "abort":
        driver.abort()
    else:
        driver.close()


def _scope_provider_problems(
    specs: list[InstrumentSpec],
    problems: tuple[Problem, ...],
) -> tuple[tuple[Problem, ...], dict[str, tuple[Problem, ...]]]:
    instrument_ids = {spec.id for spec in specs}
    scoped: dict[str, list[Problem]] = {}
    global_problems: list[Problem] = []
    for item in problems:
        owners = _problem_instrument_ids(
            item,
            specs=specs,
            instrument_ids=instrument_ids,
        )
        if not owners:
            global_problems.append(item)
            continue
        for instrument_id in owners:
            scoped.setdefault(instrument_id, []).append(item)
    return (
        tuple(global_problems),
        {instrument_id: tuple(items) for instrument_id, items in scoped.items()},
    )


def _problem_instrument_ids(
    problem: Problem,
    *,
    specs: list[InstrumentSpec],
    instrument_ids: set[str],
) -> tuple[str, ...]:
    selected: set[str] = set()
    detail_id = problem.details.get("instrument_id")
    if isinstance(detail_id, str) and detail_id in instrument_ids:
        selected.add(detail_id)
    for location in (
        *((problem.location,) if problem.location is not None else ()),
        *problem.related_locations,
    ):
        if (
            isinstance(location, RuntimeLocation)
            and location.instrument_id in instrument_ids
        ):
            assert location.instrument_id is not None
            selected.add(location.instrument_id)
        elif isinstance(location, ModelLocation):
            selected.update(
                item
                for item in location.path
                if isinstance(item, str) and item in instrument_ids
            )
            for index, item in enumerate(location.path[:-1]):
                candidate = location.path[index + 1]
                if (
                    item == "instruments"
                    and isinstance(candidate, int)
                    and candidate < len(specs)
                ):
                    selected.add(specs[candidate].id)
    return tuple(sorted(selected))


__all__ = ["InstrumentService"]

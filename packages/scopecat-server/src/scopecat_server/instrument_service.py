"""Daemon-owned direct instrument interaction sessions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import timedelta
from threading import RLock
from typing import Literal

from pydantic import JsonValue
from scopecat.adapters.sqlite import (
    ControlPlaneConflict,
    ControlPlaneNotFound,
    InstrumentSessionLeaseNotHeld,
    SQLiteControlPlane,
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
)
from scopecat.execution.local.drivers import (
    describe_instruments,
    validate_instruments,
)
from scopecat.kernel.problems import ModelLocation, Problem, RuntimeLocation
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


@dataclass(slots=True)
class _LiveSession:
    drivers: dict[str, InstrumentDriver]
    descriptions: dict[str, InstrumentDescription]
    apply_receipts: dict[str, tuple[InstrumentStateCommand, ApplyReceipt]] = field(
        default_factory=dict
    )
    collect_receipts: dict[str, tuple[CollectCommand, CollectReceipt]] = field(
        default_factory=dict
    )
    collect_failures: dict[str, tuple[CollectCommand, str]] = field(
        default_factory=dict
    )
    lock: RLock = field(default_factory=RLock)


@dataclass(frozen=True, slots=True)
class _EndedSession:
    command: InstrumentSessionEndCommand
    abort: bool
    receipt: InstrumentSessionEndReceipt


class InstrumentService:
    """Retain live drivers behind renewable daemon fencing tokens."""

    def __init__(
        self,
        *,
        control: SQLiteControlPlane,
        config: ConfigService,
        build_system: ExperimentSystemBuilder | None,
        lease_ttl: timedelta | None = None,
    ) -> None:
        self._control = control
        self._config = config
        self._build_system = build_system
        self._lease_ttl = lease_ttl or timedelta(seconds=30)
        self._heartbeat_interval_seconds = self._lease_ttl.total_seconds() / 3
        self._sessions: dict[str, _LiveSession] = {}
        self._ended_sessions: dict[str, _EndedSession] = {}
        self._sessions_lock = RLock()
        self._open_lock = RLock()
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

        drivers: tuple[InstrumentDriver, ...] = ()
        try:
            result = provider.provide(
                InstrumentProviderContext(
                    config=active.config,
                    instrument_ids=command.instrument_ids,
                )
            )
            drivers = result.drivers
            if result.problems:
                raise _ProvisioningRejected("instrument provider rejected the session")
            problems = validate_instruments(
                config=active.config,
                instruments=list(drivers),
            )
            actual, description_problems = describe_instruments(list(drivers))
            problems.extend(description_problems)
            if problems:
                raise _ProvisioningRejected(
                    "instrument provider returned invalid drivers"
                )
            actual_by_id = {
                description.instrument_id: description for description in actual
            }
            if tuple(actual_by_id) != command.instrument_ids:
                raise _ProvisioningRejected(
                    "instrument provider did not return the requested drivers in order"
                )
            for instrument_id in command.instrument_ids:
                if actual_by_id[instrument_id] != descriptions[instrument_id]:
                    raise _ProvisioningRejected(
                        f"instrument description changed while opening {instrument_id}"
                    )
        except _ProvisioningRejected as error:
            close_failed = _call_all(drivers, _close_driver)
            if close_failed:
                self._mark_unknown(
                    session,
                    reason="instrument_provisioning_cleanup_failed",
                )
            else:
                self._control.close_instrument_session(
                    session.session_id,
                    token=_session_token(session),
                )
            raise BackendConflict(str(error)) from error
        except Exception as error:
            _call_all(drivers, _abort_driver)
            _call_all(drivers, _close_driver)
            self._mark_unknown(session, reason="instrument_provisioning_unknown")
            raise BackendConflict(
                "instrument provider failed while connecting"
            ) from error

        runtime = _LiveSession(
            drivers={driver.instrument_id: driver for driver in drivers},
            descriptions=descriptions,
        )
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
            try:
                state = driver.read_state()
            except Exception as error:
                raise BackendConflict("instrument state read failed") from error
        if state.instrument_id != instrument_id:
            raise BackendConflict("instrument returned state for another instrument")
        return state

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
            validation_problems = validate_state_command(
                command=request.command,
                description=runtime.descriptions[instrument_id],
            )
            if validation_problems:
                raise BackendConflict(
                    "; ".join(item.message for item in validation_problems)
                )
            operation_id = request.command.operation_id
            assert operation_id is not None
            cached = runtime.apply_receipts.get(operation_id)
            if cached is not None:
                cached_command, cached_receipt = cached
                if cached_command != request.command:
                    raise BackendConflict(
                        "interactive operation id has different apply content"
                    )
                return cached_receipt
            if (
                operation_id in runtime.collect_receipts
                or operation_id in runtime.collect_failures
            ):
                raise BackendConflict(
                    "interactive operation id was already used for collect"
                )
            self._record_operation_started(
                session,
                instrument_id=instrument_id,
                operation_id=operation_id,
                kind="apply",
            )
            try:
                receipt = driver.apply_state(request.command)
            except Exception as error:
                self._lose_runtime(
                    session,
                    runtime,
                    reason="instrument_apply_unknown",
                )
                raise BackendConflict(
                    "instrument apply failed with unknown state"
                ) from error
            runtime.apply_receipts[operation_id] = (request.command, receipt)
            try:
                self._record_operation_finished(
                    session,
                    instrument_id=instrument_id,
                    operation_id=operation_id,
                    kind="apply",
                    status=receipt.status,
                )
            except Exception as error:
                self._lose_runtime(
                    session,
                    runtime,
                    reason="instrument_apply_audit_unknown",
                )
                raise BackendConflict(
                    "instrument apply completed but audit recording failed"
                ) from error
            if receipt.status == "unknown":
                self._lose_runtime(
                    session,
                    runtime,
                    reason="instrument_apply_receipt_unknown",
                )
        return receipt

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
            validation_problems = validate_collect_command(
                command=request.command,
                description=runtime.descriptions[instrument_id],
            )
            if validation_problems:
                raise BackendConflict(
                    "; ".join(item.message for item in validation_problems)
                )
            operation_id = request.command.operation_id
            assert operation_id is not None
            cached = runtime.collect_receipts.get(operation_id)
            if cached is not None:
                cached_command, cached_receipt = cached
                if cached_command != request.command:
                    raise BackendConflict(
                        "interactive operation id has different collect content"
                    )
                return cached_receipt
            cached_failure = runtime.collect_failures.get(operation_id)
            if cached_failure is not None:
                cached_command, cached_message = cached_failure
                if cached_command != request.command:
                    raise BackendConflict(
                        "interactive operation id has different collect content"
                    )
                raise BackendConflict(cached_message)
            if operation_id in runtime.apply_receipts:
                raise BackendConflict(
                    "interactive operation id was already used for apply"
                )
            self._record_operation_started(
                session,
                instrument_id=instrument_id,
                operation_id=operation_id,
                kind="collect",
            )
            try:
                receipt = driver.collect(request.command)
            except Exception as error:
                self._lose_runtime(
                    session,
                    runtime,
                    reason="instrument_collect_unknown",
                )
                raise BackendConflict(
                    "instrument collect failed with unknown state"
                ) from error
            receipt_problems = validate_collect_receipt(
                command=request.command,
                receipt=receipt,
            )
            if receipt_problems:
                message = "; ".join(item.message for item in receipt_problems)
                try:
                    self._record_operation_finished(
                        session,
                        instrument_id=instrument_id,
                        operation_id=operation_id,
                        kind="collect",
                        status="invalid_receipt",
                    )
                except Exception as error:
                    self._lose_runtime(
                        session,
                        runtime,
                        reason="instrument_collect_audit_unknown",
                    )
                    raise BackendConflict(
                        "instrument collect completed but audit recording failed"
                    ) from error
                runtime.collect_failures[operation_id] = (
                    request.command,
                    message,
                )
                raise BackendConflict(message)
            runtime.collect_receipts[operation_id] = (request.command, receipt)
            try:
                self._record_operation_finished(
                    session,
                    instrument_id=instrument_id,
                    operation_id=operation_id,
                    kind="collect",
                    status=receipt.status,
                )
            except Exception as error:
                self._lose_runtime(
                    session,
                    runtime,
                    reason="instrument_collect_audit_unknown",
                )
                raise BackendConflict(
                    "instrument collect completed but audit recording failed"
                ) from error
            if receipt.status == "unknown":
                self._lose_runtime(
                    session,
                    runtime,
                    reason="instrument_collect_receipt_unknown",
                )
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
        try:
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
            runtime = self._pop_runtime(session_id)
            if runtime is None:
                continue
            with runtime.lock:
                _call_all(runtime.drivers.values(), _abort_driver)
                _call_all(runtime.drivers.values(), _close_driver)

    def reconcile_startup(self) -> None:
        self._control.abandon_instrument_sessions()

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
    ) -> tuple[InstrumentSession, _LiveSession, InstrumentDriver]:
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

    def _live_runtime(self, session_id: str) -> _LiveSession:
        with self._sessions_lock:
            runtime = self._sessions.get(session_id)
        if runtime is None:
            raise BackendConflict("instrument session has no live daemon drivers")
        return runtime

    def _pop_runtime(self, session_id: str) -> _LiveSession | None:
        with self._sessions_lock:
            return self._sessions.pop(session_id, None)

    def _lose_runtime(
        self,
        session: InstrumentSession,
        runtime: _LiveSession,
        *,
        reason: str,
    ) -> None:
        _call_all(runtime.drivers.values(), _abort_driver)
        _call_all(runtime.drivers.values(), _close_driver)
        self._pop_runtime(session.session_id)
        self._mark_unknown(session, reason=reason)

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
        runtime: _LiveSession,
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
    pass


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

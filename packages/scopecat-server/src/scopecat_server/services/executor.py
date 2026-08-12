"""Fenced executor application service."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import JsonValue, RootModel
from scopecat.control.models import (
    ControlRun,
    DurableEventInput,
)
from scopecat.control.models import (
    ExecutorLease as ControlExecutorLease,
)
from scopecat.daemon.wire import (
    ExecutionTransitionAppend,
    ExecutionTransitionClaim,
    ExecutorHeartbeat,
    ExecutorLease,
    ExecutorStartRequest,
    MeasurementAppendCommand,
    MeasurementHeaderCommand,
    MeasurementSealCommand,
    RunCancellationReceipt,
    TerminalRunCommitCommand,
)
from scopecat.kernel.problems import ProblemPhase, problem
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.measurement_recording import MeasurementDatasetReceipt
from scopecat.records.run import RunManifest
from scopecat.runs.repository import (
    RunModelWrite,
    TerminalRunCommit,
)
from scopecat.runs.terminal import merge_terminal_manifest

from scopecat_server.storage.sqlite.control_plane import (
    ControlPlaneConflict,
    ControlPlaneNotFound,
    ExecutorLeaseNotHeld,
    SQLiteControlPlane,
)
from scopecat_server.storage.sqlite.execution import (
    ExecutionJournalConflict,
    SQLiteExecutionJournal,
    SQLiteMeasurementDatasetRepository,
)
from scopecat_server.storage.sqlite.run_repository import SQLiteRunRepository

from ..errors import BackendConflict, BackendNotFound

if TYPE_CHECKING:
    from ..instruments.service import InstrumentService


class _JsonDocument(RootModel[dict[str, JsonValue]]):
    pass


class ExecutorService:
    """Own executor leases and every fenced durable execution write."""

    def __init__(
        self,
        *,
        control: SQLiteControlPlane,
        runs: SQLiteRunRepository,
        instruments: InstrumentService,
        lease_ttl: timedelta | None = None,
    ) -> None:
        self._control = control
        self._runs = runs
        self._instruments = instruments
        self._lease_ttl = lease_ttl or timedelta(seconds=30)
        self._heartbeat_interval_seconds = self._lease_ttl.total_seconds() / 3
        self._measurement_repositories: dict[
            str, SQLiteMeasurementDatasetRepository
        ] = {}

    def _control_run(self, run_id: str) -> ControlRun:
        try:
            return self._control.get_run(run_id)
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error

    def start_executor(
        self,
        run_id: str,
        request: ExecutorStartRequest,
    ) -> ExecutorLease:
        return self._start_execution(
            run_id,
            executor_id=request.executor_id,
        )

    def heartbeat_executor(
        self,
        run_id: str,
        heartbeat: ExecutorHeartbeat,
    ) -> ExecutorLease:
        try:
            renewed = self._control.renew_executor_lease(
                run_id,
                heartbeat.lease_id,
                ttl=self._lease_ttl,
            )
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error
        current = self._control_run(run_id)
        return self._wire_lease(
            renewed,
            cancellation_requested_at=current.cancellation_requested_at,
        )

    def cancel_run(self, run_id: str) -> RunCancellationReceipt:
        """Cancel queued work now or request a leased executor checkpoint stop."""

        requested_at = datetime.now(tz=UTC)
        outcome = RunOutcome(
            run_id=run_id,
            result="cancelled",
            certainty="known",
            finished_at=requested_at,
            problems=(
                problem(
                    "run_cancelled_before_execution",
                    "run was cancelled before execution started",
                    phase=ProblemPhase.EXECUTION,
                ),
            ),
        )
        prepared = self._runs.prepare_terminal_commit(
            TerminalRunCommit(run_id=run_id, outcome=outcome)
        )
        try:
            with self._control.write_transaction() as connection:
                current = self._control.get_run_in_transaction(connection, run_id)
                manifest = self._runs.read_manifest_in_transaction(connection, run_id)
                if current.state == "closed":
                    return _cancellation_receipt(current, manifest)
                if current.state == "attention_required":
                    raise ControlPlaneConflict(
                        "attention-required run must be reconciled before it can close"
                    )
                current = self._control.request_run_cancellation_in_transaction(
                    connection,
                    run_id,
                    at=requested_at,
                )
                if current.state == "leased":
                    return RunCancellationReceipt(
                        run_id=run_id,
                        status="cancel_requested",
                        cancellation_requested_at=current.cancellation_requested_at,
                    )
                manifest = self._runs.commit_prepared_terminal_in_transaction(
                    connection,
                    prepared,
                )
                current = self._control.close_run_in_transaction(
                    connection,
                    run_id,
                    at=requested_at,
                )
                return _cancellation_receipt(current, manifest)
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error

    def append_transition(
        self,
        run_id: str,
        command: ExecutionTransitionAppend,
    ) -> ExecutionTransition:
        journal = SQLiteExecutionJournal(self._runs, run_id=run_id)
        with self.fenced_write(
            run_id,
            token=command.lease_id,
        ) as connection:
            transition, _created = journal.append_in_transaction(
                connection,
                command.transition,
            )
        return transition

    def claim_transition(
        self,
        run_id: str,
        command: ExecutionTransitionClaim,
    ) -> ExecutionTransition:
        journal = SQLiteExecutionJournal(self._runs, run_id=run_id)
        try:
            with self.fenced_write(
                run_id,
                token=command.lease_id,
            ) as connection:
                return journal.claim_in_transaction(connection, command.transition)
        except ExecutionJournalConflict as error:
            raise BackendConflict(str(error)) from error

    def append_measurements(
        self,
        run_id: str,
        command: MeasurementAppendCommand,
    ) -> MeasurementDatasetReceipt:
        repository = self._measurement_repository(run_id)
        try:
            prepared = repository.prepare_append(command.append)
        except ExecutionJournalConflict as error:
            raise BackendConflict(
                "measurement command conflicts with durable state"
            ) from error
        with self.fenced_write(
            run_id,
            token=command.lease_id,
        ) as connection:
            receipt, created = repository.append_prepared_in_transaction(
                connection,
                prepared,
            )
            if created:
                self.append_effect_event_in_transaction(
                    connection,
                    run_id,
                    "measurements_appended",
                    command.append.operation_id,
                )
        return receipt

    def initialize_measurements(
        self,
        run_id: str,
        command: MeasurementHeaderCommand,
    ) -> MeasurementDatasetReceipt:
        repository = self._measurement_repository(run_id)
        try:
            prepared = repository.prepare_header(command.header)
        except ExecutionJournalConflict as error:
            raise BackendConflict(
                "measurement command conflicts with durable state"
            ) from error
        with self.fenced_write(
            run_id,
            token=command.lease_id,
        ) as connection:
            receipt, created = repository.header_prepared_in_transaction(
                connection,
                prepared,
            )
            if created:
                self.append_effect_event_in_transaction(
                    connection,
                    run_id,
                    "measurement_dataset_initialized",
                    command.header.operation_id,
                )
        return receipt

    def seal_measurements(
        self,
        run_id: str,
        command: MeasurementSealCommand,
    ) -> MeasurementDatasetReceipt:
        repository = self._measurement_repository(run_id)
        try:
            prepared = repository.prepare_seal(command.seal)
        except ExecutionJournalConflict as error:
            raise BackendConflict(
                "measurement command conflicts with durable state"
            ) from error
        with self.fenced_write(
            run_id,
            token=command.lease_id,
        ) as connection:
            receipt, created = repository.seal_prepared_in_transaction(
                connection,
                prepared,
            )
            if created:
                self.append_effect_event_in_transaction(
                    connection,
                    run_id,
                    "measurements_sealed",
                    command.seal.operation_id,
                )
        self._measurement_repositories.pop(run_id, None)
        return receipt

    def _measurement_repository(
        self,
        run_id: str,
    ) -> SQLiteMeasurementDatasetRepository:
        repository = self._measurement_repositories.get(run_id)
        if repository is None:
            repository = SQLiteMeasurementDatasetRepository(
                self._runs,
                run_id=run_id,
            )
            self._measurement_repositories[run_id] = repository
        return repository

    def commit_terminal(
        self,
        run_id: str,
        command: TerminalRunCommitCommand,
    ) -> RunManifest:
        commit = TerminalRunCommit(
            run_id=run_id,
            outcome=command.outcome,
            contents=command.contents,
            models=tuple(
                RunModelWrite(
                    ref=write.ref,
                    value=_JsonDocument(root=write.value),
                )
                for write in command.models
            ),
        )
        control_run = self._control_run(run_id)
        commit = _honor_cancellation(control_run, commit)
        if control_run.state == "closed":
            manifest = self._runs.read_manifest(run_id)
            if not _matches_terminal_intent(manifest, commit):
                raise BackendConflict("run already has a different terminal outcome")
            self._instruments.release_run(run_id)
            self._measurement_repositories.pop(run_id, None)
            return manifest
        self._instruments.finalize_run(
            run_id,
            token=command.lease_id,
        )
        try:
            manifest = self.commit_terminal_with_authority(
                run_id,
                token=command.lease_id,
                commit=commit,
            )
        except BackendConflict:
            current = self._control_run(run_id)
            manifest = self._runs.read_manifest(run_id)
            if current.state != "closed" or not _matches_terminal_intent(
                manifest,
                commit,
            ):
                raise
        self._instruments.release_run(run_id)
        self._measurement_repositories.pop(run_id, None)
        return manifest

    def _start_execution(
        self,
        run_id: str,
        *,
        executor_id: str,
    ) -> ExecutorLease:
        try:
            with self._control.write_transaction() as connection:
                current = self._control.get_run_in_transaction(connection, run_id)
                latest_manifest = self._runs.read_manifest_in_transaction(
                    connection,
                    run_id,
                )
                if current.state == "leased":
                    lease = self._control.executor_lease_for_run_in_transaction(
                        connection,
                        run_id,
                    )
                    if (
                        lease is None
                        or lease.expires_at <= datetime.now(tz=UTC)
                        or lease.executor_id != executor_id
                        or latest_manifest.outcome is not None
                    ):
                        raise ControlPlaneConflict(
                            "run is already owned by a different executor intent"
                        )
                    return self._wire_lease(
                        lease,
                        cancellation_requested_at=current.cancellation_requested_at,
                    )
                if latest_manifest.outcome is not None:
                    raise ControlPlaneConflict(
                        "run manifest is not ready to start execution"
                    )
                lease = self._control.start_execution_in_transaction(
                    connection,
                    run_id,
                    executor_id=executor_id,
                    ttl=self._lease_ttl,
                )
                return self._wire_lease(
                    lease,
                    cancellation_requested_at=current.cancellation_requested_at,
                )
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error

    def fence_executor(self, run_id: str, token: str) -> str:
        try:
            self._control.validate_executor_lease(
                run_id,
                token=token,
            )
        except ExecutorLeaseNotHeld as error:
            raise BackendConflict(
                "executor lease is absent, stale, or expired"
            ) from error
        return token

    @contextmanager
    def fenced_write(
        self,
        run_id: str,
        *,
        token: str,
    ) -> Generator[sqlite3.Connection]:
        try:
            with self._control.fenced_transaction(
                run_id,
                token=token,
            ) as connection:
                yield connection
        except (
            ControlPlaneConflict,
            ExecutionJournalConflict,
        ) as error:
            raise BackendConflict(
                "executor command conflicts with durable run state"
            ) from error

    def _wire_lease(
        self,
        lease: ControlExecutorLease,
        *,
        cancellation_requested_at: datetime | None,
    ) -> ExecutorLease:
        return ExecutorLease(
            lease_id=lease.token,
            run_id=lease.run_id,
            executor_id=lease.executor_id,
            issued_at=lease.acquired_at,
            expires_at=lease.expires_at,
            heartbeat_interval_seconds=self._heartbeat_interval_seconds,
            cancellation_requested_at=cancellation_requested_at,
        )

    def append_effect_event_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        kind: str,
        operation_id: str,
    ) -> None:
        self._control.append_event_in_transaction(
            connection,
            DurableEventInput(
                run_id=run_id,
                kind=kind,
                payload={"operation_id": operation_id},
            ),
        )

    def commit_terminal_with_authority(
        self,
        run_id: str,
        *,
        token: str,
        commit: TerminalRunCommit,
    ) -> RunManifest:
        prepared = self._runs.prepare_terminal_commit(commit)
        with self.fenced_write(
            run_id,
            token=token,
        ) as connection:
            control = self._control.get_run_in_transaction(connection, run_id)
            commit = _honor_cancellation(control, commit)
            prepared = replace(prepared, commit=commit)
            manifest = self._runs.commit_prepared_terminal_in_transaction(
                connection,
                prepared,
            )
            self._control.close_run_in_transaction(
                connection,
                run_id,
                executor_token=token,
            )
            return manifest


def _matches_terminal_intent(
    current: RunManifest,
    commit: TerminalRunCommit,
) -> bool:
    if current.outcome != commit.outcome:
        return False
    try:
        return (
            merge_terminal_manifest(
                current,
                run_id=commit.run_id,
                outcome=commit.outcome,
                contents=commit.contents,
            )
            == current
        )
    except ValueError:
        return False


def _cancellation_receipt(
    control: ControlRun,
    manifest: RunManifest,
) -> RunCancellationReceipt:
    outcome = manifest.outcome
    if outcome is None:
        raise AssertionError("closed cancellation receipt requires a terminal outcome")
    requested_at = control.cancellation_requested_at
    status = (
        "cancelled"
        if requested_at is not None and outcome.result == "cancelled"
        else "not_accepted"
    )
    return RunCancellationReceipt(
        run_id=control.run_id,
        status=status,
        cancellation_requested_at=requested_at,
        outcome=outcome,
    )


def _honor_cancellation(
    control: ControlRun,
    commit: TerminalRunCommit,
) -> TerminalRunCommit:
    requested_at = control.cancellation_requested_at
    if requested_at is None or commit.outcome.result != "succeeded":
        return commit
    return replace(
        commit,
        outcome=RunOutcome(
            run_id=commit.run_id,
            result="cancelled",
            certainty="known",
            finished_at=commit.outcome.finished_at,
            problems=(
                problem(
                    "run_cancellation_requested",
                    "run cancellation won the terminal commit race",
                    phase=ProblemPhase.EXECUTION,
                ),
            ),
        ),
    )

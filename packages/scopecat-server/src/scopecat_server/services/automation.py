"""Application service for durable multi-run procedure coordination."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from scopecat.automation import (
    ProcedureCloseCommand,
    ProcedureCloseReceipt,
    ProcedureCloseStatus,
    ProcedureClosure,
    ProcedureDefinitionRef,
    ProcedureIntent,
    ProcedureRun,
    ProcedureRunAttentionCommand,
    ProcedureRunAttentionReceipt,
    ProcedureRunListQuery,
    ProcedureRunPage,
    ProcedureRunState,
    ProcedureStepAttempt,
    ProcedureStepAttemptListQuery,
    ProcedureStepAttemptPage,
    ProcedureStepAttemptState,
    ProcedureStepAttentionCommand,
    ProcedureStepAttentionReceipt,
    ProcedureStepBeginCommand,
    ProcedureStepBeginReceipt,
    ProcedureStepCompleteCommand,
    ProcedureStepCompleteReceipt,
    ProcedureStepFailCommand,
    ProcedureStepFailReceipt,
    ProcedureStepOperation,
    ProcedureStepOutputRef,
    ProcedureSubmitCommand,
    ProcedureSubmitReceipt,
    ProcedureWaitCommand,
    ProcedureWaitCondition,
    ProcedureWaitReceipt,
    ProcedureWorkerLease,
    ProcedureWorkerLeaseAcquireCommand,
    ProcedureWorkerLeaseAcquireReceipt,
    ProcedureWorkerLeaseHeartbeatCommand,
    ProcedureWorkerLeaseHeartbeatReceipt,
    ProcedureWorkerLeaseReleaseCommand,
    ProcedureWorkerLeaseReleaseReceipt,
    procedure_intent_hash,
    procedure_step_operation_id,
)
from scopecat.records.content import Sha256ContentHash

from scopecat_server.storage.sqlite.automation import (
    AutomationConflict,
    AutomationNotFound,
    ProcedureLeaseRecord,
    SQLiteAutomationStore,
)
from scopecat_server.storage.sqlite.automation import (
    ProcedureRunPage as StoredProcedureRunPage,
)
from scopecat_server.storage.sqlite.automation import (
    ProcedureStepAttemptPage as StoredProcedureStepAttemptPage,
)

from ..errors import BackendConflict, BackendNotFound

_DEFAULT_PROCEDURE_LEASE_TTL = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class ProcedureStepTransition:
    """Atomic procedure and step snapshots returned by a step command."""

    run: ProcedureRun
    attempt: ProcedureStepAttempt


class AutomationService:
    """Own procedure admission, revision CAS, and worker fencing."""

    def __init__(
        self,
        store: SQLiteAutomationStore,
        *,
        lease_ttl: timedelta = _DEFAULT_PROCEDURE_LEASE_TTL,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if lease_ttl <= timedelta(0):
            raise ValueError("procedure lease TTL must be positive")
        self._store = store
        self._lease_ttl = lease_ttl
        self._clock = clock or _utc_now

    def submit(self, command: ProcedureSubmitCommand) -> ProcedureSubmitReceipt:
        return ProcedureSubmitReceipt(
            run=self._submit(
                definition=command.definition,
                request_key=command.request_key,
                intent=command.intent,
            )
        )

    def list(self, query: ProcedureRunListQuery) -> ProcedureRunPage:
        page = self._list(
            limit=query.limit,
            before=query.cursor,
            state=query.state,
        )
        return ProcedureRunPage(items=page.items, next_cursor=page.next_cursor)

    def step_attempts(
        self,
        procedure_run_id: str,
        query: ProcedureStepAttemptListQuery,
    ) -> ProcedureStepAttemptPage:
        page = self._step_attempts(
            procedure_run_id,
            limit=query.limit,
            before=query.cursor,
        )
        return ProcedureStepAttemptPage(
            procedure_run_id=procedure_run_id,
            items=page.items,
            next_cursor=page.next_cursor,
        )

    def acquire_lease(
        self,
        command: ProcedureWorkerLeaseAcquireCommand,
    ) -> ProcedureWorkerLeaseAcquireReceipt:
        lease = self._acquire_lease(
            command.procedure_run_id,
            worker_id=command.worker_id,
            expected_revision=command.expected_run_revision,
        )
        return ProcedureWorkerLeaseAcquireReceipt(
            run=self.get(command.procedure_run_id),
            lease=self._wire_lease(lease),
        )

    def heartbeat_lease(
        self,
        command: ProcedureWorkerLeaseHeartbeatCommand,
    ) -> ProcedureWorkerLeaseHeartbeatReceipt:
        lease = self._renew_lease(
            command.procedure_run_id,
            token=command.lease_token,
        )
        return ProcedureWorkerLeaseHeartbeatReceipt(
            run=self.get(command.procedure_run_id),
            lease=self._wire_lease(lease),
        )

    def release_lease(
        self,
        command: ProcedureWorkerLeaseReleaseCommand,
    ) -> ProcedureWorkerLeaseReleaseReceipt:
        return ProcedureWorkerLeaseReleaseReceipt(
            run=self._release_lease(
                command.procedure_run_id,
                token=command.lease_token,
                expected_revision=command.expected_run_revision,
            )
        )

    def begin_step(
        self,
        command: ProcedureStepBeginCommand,
    ) -> ProcedureStepBeginReceipt:
        transition = self._begin_step(
            command.procedure_run_id,
            token=command.lease_token,
            expected_run_revision=command.expected_run_revision,
            step_key=command.step_key,
            operation=command.operation,
            intent_hash=command.intent_hash,
            inputs=command.inputs,
        )
        return ProcedureStepBeginReceipt(
            run=transition.run,
            step=transition.attempt,
            operation_id=procedure_step_operation_id(
                transition.attempt.procedure_run_id,
                transition.attempt.step_key,
                transition.attempt.attempt,
            ),
        )

    def complete_step(
        self,
        command: ProcedureStepCompleteCommand,
    ) -> ProcedureStepCompleteReceipt:
        transition = self._complete_step(
            command.procedure_run_id,
            token=command.lease_token,
            expected_run_revision=command.expected_run_revision,
            step_key=command.step_key,
            attempt=command.attempt,
            expected_attempt_revision=command.expected_step_revision,
            output=command.output,
        )
        return ProcedureStepCompleteReceipt(
            run=transition.run,
            step=transition.attempt,
        )

    def fail_step(
        self,
        command: ProcedureStepFailCommand,
    ) -> ProcedureStepFailReceipt:
        transition = self._fail_step(
            command.procedure_run_id,
            token=command.lease_token,
            expected_run_revision=command.expected_run_revision,
            step_key=command.step_key,
            attempt=command.attempt,
            expected_attempt_revision=command.expected_step_revision,
            reason=command.reason,
        )
        return ProcedureStepFailReceipt(
            run=transition.run,
            step=transition.attempt,
        )

    def require_step_attention(
        self,
        command: ProcedureStepAttentionCommand,
    ) -> ProcedureStepAttentionReceipt:
        transition = self._require_step_attention(
            command.procedure_run_id,
            token=command.lease_token,
            expected_run_revision=command.expected_run_revision,
            step_key=command.step_key,
            attempt=command.attempt,
            expected_attempt_revision=command.expected_step_revision,
            reason=command.reason,
        )
        return ProcedureStepAttentionReceipt(
            run=transition.run,
            step=transition.attempt,
        )

    def require_run_attention(
        self,
        command: ProcedureRunAttentionCommand,
    ) -> ProcedureRunAttentionReceipt:
        return ProcedureRunAttentionReceipt(
            run=self._require_run_attention(
                command.procedure_run_id,
                token=command.lease_token,
                expected_revision=command.expected_run_revision,
                reason=command.reason,
            )
        )

    def wait(self, command: ProcedureWaitCommand) -> ProcedureWaitReceipt:
        return ProcedureWaitReceipt(
            run=self._wait(
                command.procedure_run_id,
                token=command.lease_token,
                expected_revision=command.expected_run_revision,
                condition=command.condition,
            )
        )

    def close(self, command: ProcedureCloseCommand) -> ProcedureCloseReceipt:
        return ProcedureCloseReceipt(
            run=self._close(
                command.procedure_run_id,
                token=command.lease_token,
                expected_revision=command.expected_run_revision,
                status=command.status,
                reason=command.reason,
            )
        )

    def _submit(
        self,
        *,
        definition: ProcedureDefinitionRef,
        request_key: str,
        intent: ProcedureIntent,
    ) -> ProcedureRun:
        """Admit one idempotent, version-pinned procedure request."""

        if not request_key.strip():
            raise ValueError("procedure request key must be non-empty")
        selected_intent = dict(intent)
        intent_hash = procedure_intent_hash(definition, selected_intent)
        with (
            _translate_store_errors(),
            self._store.write_transaction() as connection,
        ):
            existing = self._store.find_run_by_request_in_transaction(
                connection,
                definition.id,
                request_key,
            )
            if existing is not None:
                if existing.intent_hash != intent_hash:
                    raise AutomationConflict(
                        "procedure request key already has different intent"
                    )
                return existing
            now = self._now()
            run = ProcedureRun(
                procedure_run_id=f"procedure-{uuid4().hex}",
                request_key=request_key,
                definition=definition,
                intent=selected_intent,
                intent_hash=intent_hash,
                revision=1,
                state="ready",
                created_at=now,
                updated_at=now,
            )
            self._store.insert_run_in_transaction(connection, run)
            return run

    def get(self, procedure_run_id: str) -> ProcedureRun:
        with _translate_store_errors():
            return self._store.read_run(procedure_run_id)

    def _list(
        self,
        *,
        limit: int = 50,
        before: int | None = None,
        state: ProcedureRunState | None = None,
    ) -> StoredProcedureRunPage:
        return self._store.list_runs(limit=limit, before=before, state=state)

    def _step_attempts(
        self,
        procedure_run_id: str,
        *,
        limit: int = 100,
        before: int | None = None,
    ) -> StoredProcedureStepAttemptPage:
        with _translate_store_errors():
            return self._store.list_step_attempts(
                procedure_run_id,
                limit=limit,
                before=before,
            )

    def _acquire_lease(
        self,
        procedure_run_id: str,
        *,
        worker_id: str,
        expected_revision: int,
    ) -> ProcedureLeaseRecord:
        """Lease a ready run or take over an expired worker lease."""

        if not worker_id.strip():
            raise ValueError("procedure worker id must be non-empty")
        now = self._now()
        with (
            _translate_store_errors(),
            self._store.write_transaction() as connection,
        ):
            run = self._store.read_run_in_transaction(connection, procedure_run_id)
            current_lease = self._store.read_lease_in_transaction(
                connection,
                procedure_run_id,
            )
            if (
                run.state == "leased"
                and current_lease is not None
                and current_lease.expires_at > now
                and current_lease.worker_id == worker_id
                and run.revision == expected_revision + 1
            ):
                return current_lease
            self._require_revision(run, expected_revision)
            if run.state == "ready":
                pass
            elif run.state == "leased":
                if current_lease is not None and current_lease.expires_at > now:
                    raise AutomationConflict("procedure run already has a live lease")
            else:
                raise AutomationConflict(
                    "procedure lease requires ready or expired leased state, "
                    f"got {run.state}"
                )
            updated = _run_state(run, state="leased", at=now)
            self._store.replace_run_in_transaction(
                connection,
                updated,
                expected_revision=expected_revision,
            )
            lease = ProcedureLeaseRecord(
                procedure_run_id=procedure_run_id,
                worker_id=worker_id,
                token=uuid4().hex,
                acquired_at=now,
                renewed_at=now,
                expires_at=now + self._lease_ttl,
            )
            self._store.put_lease_in_transaction(connection, lease)
            return lease

    def _renew_lease(
        self,
        procedure_run_id: str,
        *,
        token: str,
    ) -> ProcedureLeaseRecord:
        """Renew a live lease without changing procedure business revision."""

        now = self._now()
        with (
            _translate_store_errors(),
            self._store.write_transaction() as connection,
        ):
            run = self._store.read_run_in_transaction(connection, procedure_run_id)
            if run.state != "leased":
                raise AutomationConflict("only a leased procedure can renew")
            lease = self._require_live_lease(
                connection,
                procedure_run_id,
                token,
                now,
            )
            renewed = ProcedureLeaseRecord(
                procedure_run_id=lease.procedure_run_id,
                worker_id=lease.worker_id,
                token=lease.token,
                acquired_at=lease.acquired_at,
                renewed_at=now,
                expires_at=now + self._lease_ttl,
            )
            self._store.put_lease_in_transaction(connection, renewed)
            return renewed

    def _release_lease(
        self,
        procedure_run_id: str,
        *,
        token: str,
        expected_revision: int,
    ) -> ProcedureRun:
        """Yield a clean procedure checkpoint back to the ready queue."""

        now = self._now()
        with (
            _translate_store_errors(),
            self._store.write_transaction() as connection,
        ):
            run = self._store.read_run_in_transaction(connection, procedure_run_id)
            lease = self._store.read_lease_in_transaction(
                connection,
                procedure_run_id,
            )
            if run.state == "ready" and lease is None:
                return run
            self._require_revision(run, expected_revision)
            if run.state != "leased":
                raise AutomationConflict("only a leased procedure can be released")
            self._require_live_lease(
                connection,
                procedure_run_id,
                token,
                now,
            )
            updated = _run_state(run, state="ready", at=now)
            self._store.replace_run_in_transaction(
                connection,
                updated,
                expected_revision=expected_revision,
            )
            self._store.delete_lease_in_transaction(
                connection,
                procedure_run_id,
                token=token,
            )
            return updated

    def _begin_step(
        self,
        procedure_run_id: str,
        *,
        token: str,
        expected_run_revision: int,
        step_key: str,
        operation: ProcedureStepOperation,
        intent_hash: Sha256ContentHash,
        inputs: tuple[ProcedureStepOutputRef, ...] = (),
    ) -> ProcedureStepTransition:
        """Begin one stable step or replay its existing durable attempt."""

        now = self._now()
        with (
            _translate_store_errors(),
            self._store.write_transaction() as connection,
        ):
            run = self._leased_run(
                connection,
                procedure_run_id,
                token=token,
                at=now,
            )
            existing = self._store.latest_step_attempt_in_transaction(
                connection,
                procedure_run_id,
                step_key,
            )
            if existing is not None:
                if (
                    existing.operation != operation
                    or existing.intent_hash != intent_hash
                    or existing.inputs != inputs
                ):
                    raise AutomationConflict(
                        "procedure step key already has different intent"
                    )
                if existing.state in {"running", "succeeded"}:
                    return ProcedureStepTransition(run=run, attempt=existing)
                raise AutomationConflict(
                    "failed or attention-required procedure step needs explicit retry"
                )
            self._require_revision(run, expected_run_revision)
            running = self._store.running_step_attempt_in_transaction(
                connection,
                procedure_run_id,
            )
            if running is not None:
                raise AutomationConflict(
                    f"procedure step is already running: {running.step_key}"
                )
            attempt = ProcedureStepAttempt(
                procedure_run_id=procedure_run_id,
                step_key=step_key,
                attempt=1,
                operation=operation,
                intent_hash=intent_hash,
                inputs=inputs,
                revision=1,
                state="running",
                started_at=now,
                updated_at=now,
            )
            updated_run = _run_state(run, state="leased", at=now)
            self._store.insert_step_attempt_in_transaction(connection, attempt)
            self._store.replace_run_in_transaction(
                connection,
                updated_run,
                expected_revision=expected_run_revision,
            )
            return ProcedureStepTransition(run=updated_run, attempt=attempt)

    def _complete_step(
        self,
        procedure_run_id: str,
        *,
        token: str,
        expected_run_revision: int,
        step_key: str,
        attempt: int,
        expected_attempt_revision: int,
        output: ProcedureStepOutputRef,
    ) -> ProcedureStepTransition:
        """Commit one exact side-effect output while retaining the worker lease."""

        now = self._now()
        with (
            _translate_store_errors(),
            self._store.write_transaction() as connection,
        ):
            run = self._leased_run(
                connection,
                procedure_run_id,
                token=token,
                at=now,
            )
            current = self._store.read_step_attempt_in_transaction(
                connection,
                procedure_run_id,
                step_key,
                attempt,
            )
            if current.state == "succeeded":
                if current.output != output:
                    raise AutomationConflict(
                        "procedure step completion has different output"
                    )
                return ProcedureStepTransition(run=run, attempt=current)
            self._require_revision(run, expected_run_revision)
            self._require_attempt_revision(current, expected_attempt_revision)
            if current.state != "running":
                raise AutomationConflict("only a running procedure step can complete")
            updated_attempt = _attempt_state(
                current,
                state="succeeded",
                at=now,
                output=output,
            )
            updated_run = _run_state(run, state="leased", at=now)
            self._store.replace_step_attempt_in_transaction(
                connection,
                updated_attempt,
                expected_revision=expected_attempt_revision,
            )
            self._store.replace_run_in_transaction(
                connection,
                updated_run,
                expected_revision=expected_run_revision,
            )
            return ProcedureStepTransition(
                run=updated_run,
                attempt=updated_attempt,
            )

    def _require_run_attention(
        self,
        procedure_run_id: str,
        *,
        token: str,
        expected_revision: int,
        reason: str,
    ) -> ProcedureRun:
        """Fence a leased run when no exact step can safely own the failure."""

        if not reason.strip():
            raise ValueError("procedure attention reason must be non-empty")
        now = self._now()
        with (
            _translate_store_errors(),
            self._store.write_transaction() as connection,
        ):
            run = self._store.read_run_in_transaction(connection, procedure_run_id)
            lease = self._store.read_lease_in_transaction(connection, procedure_run_id)
            if (
                run.state == "attention_required"
                and run.attention_reason == reason
                and lease is None
            ):
                return run
            self._require_revision(run, expected_revision)
            if run.state != "leased":
                raise AutomationConflict(
                    "procedure run attention requires a leased run"
                )
            self._require_live_lease(
                connection,
                procedure_run_id,
                token,
                now,
            )
            if (
                self._store.running_step_attempt_in_transaction(
                    connection,
                    procedure_run_id,
                )
                is not None
            ):
                raise AutomationConflict(
                    "running step attention must use the step attention command"
                )
            updated = _run_state(
                run,
                state="attention_required",
                at=now,
                attention_reason=reason,
            )
            self._store.replace_run_in_transaction(
                connection,
                updated,
                expected_revision=expected_revision,
            )
            self._store.delete_lease_in_transaction(
                connection,
                procedure_run_id,
                token=token,
            )
            return updated

    def _fail_step(
        self,
        procedure_run_id: str,
        *,
        token: str,
        expected_run_revision: int,
        step_key: str,
        attempt: int,
        expected_attempt_revision: int,
        reason: str,
    ) -> ProcedureStepTransition:
        """Record a known step failure without inventing an automatic retry."""

        if not reason.strip():
            raise ValueError("procedure step failure reason must be non-empty")
        now = self._now()
        with (
            _translate_store_errors(),
            self._store.write_transaction() as connection,
        ):
            run = self._leased_run(
                connection,
                procedure_run_id,
                token=token,
                at=now,
            )
            current = self._store.read_step_attempt_in_transaction(
                connection,
                procedure_run_id,
                step_key,
                attempt,
            )
            if current.state == "failed":
                if current.failure_reason != reason:
                    raise AutomationConflict(
                        "procedure step failure has a different reason"
                    )
                return ProcedureStepTransition(run=run, attempt=current)
            self._require_revision(run, expected_run_revision)
            self._require_attempt_revision(current, expected_attempt_revision)
            if current.state != "running":
                raise AutomationConflict("only a running procedure step can fail")
            updated_attempt = _attempt_state(
                current,
                state="failed",
                at=now,
                failure_reason=reason,
            )
            updated_run = _run_state(run, state="leased", at=now)
            self._store.replace_step_attempt_in_transaction(
                connection,
                updated_attempt,
                expected_revision=expected_attempt_revision,
            )
            self._store.replace_run_in_transaction(
                connection,
                updated_run,
                expected_revision=expected_run_revision,
            )
            return ProcedureStepTransition(
                run=updated_run,
                attempt=updated_attempt,
            )

    def _require_step_attention(
        self,
        procedure_run_id: str,
        *,
        token: str,
        expected_run_revision: int,
        step_key: str,
        attempt: int,
        expected_attempt_revision: int,
        reason: str,
    ) -> ProcedureStepTransition:
        """Fence the worker and atomically quarantine its running step and run."""

        if not reason.strip():
            raise ValueError("procedure attention reason must be non-empty")
        now = self._now()
        with (
            _translate_store_errors(),
            self._store.write_transaction() as connection,
        ):
            run = self._store.read_run_in_transaction(connection, procedure_run_id)
            current = self._store.read_step_attempt_in_transaction(
                connection,
                procedure_run_id,
                step_key,
                attempt,
            )
            if (
                run.state == "attention_required"
                and run.attention_reason == reason
                and current.state == "attention_required"
                and current.attention_reason == reason
            ):
                return ProcedureStepTransition(run=run, attempt=current)
            self._require_revision(run, expected_run_revision)
            self._require_attempt_revision(current, expected_attempt_revision)
            if run.state != "leased" or current.state != "running":
                raise AutomationConflict(
                    "procedure attention requires a leased run and running step"
                )
            self._require_live_lease(
                connection,
                procedure_run_id,
                token,
                now,
            )
            updated_attempt = _attempt_state(
                current,
                state="attention_required",
                at=now,
                attention_reason=reason,
            )
            updated_run = _run_state(
                run,
                state="attention_required",
                at=now,
                attention_reason=reason,
            )
            self._store.replace_step_attempt_in_transaction(
                connection,
                updated_attempt,
                expected_revision=expected_attempt_revision,
            )
            self._store.replace_run_in_transaction(
                connection,
                updated_run,
                expected_revision=expected_run_revision,
            )
            self._store.delete_lease_in_transaction(
                connection,
                procedure_run_id,
                token=token,
            )
            return ProcedureStepTransition(
                run=updated_run,
                attempt=updated_attempt,
            )

    def _wait(
        self,
        procedure_run_id: str,
        *,
        token: str,
        expected_revision: int,
        condition: ProcedureWaitCondition,
    ) -> ProcedureRun:
        """Persist one exact wake condition and release worker authority."""

        now = self._now()
        with (
            _translate_store_errors(),
            self._store.write_transaction() as connection,
        ):
            run = self._store.read_run_in_transaction(connection, procedure_run_id)
            lease = self._store.read_lease_in_transaction(
                connection,
                procedure_run_id,
            )
            if (
                run.state == "waiting"
                and run.wait_condition == condition
                and lease is None
            ):
                return run
            self._require_revision(run, expected_revision)
            if run.state != "leased":
                raise AutomationConflict("only a leased procedure can wait")
            self._require_live_lease(
                connection,
                procedure_run_id,
                token,
                now,
            )
            if (
                self._store.running_step_attempt_in_transaction(
                    connection,
                    procedure_run_id,
                )
                is not None
            ):
                raise AutomationConflict(
                    "procedure cannot wait while a step attempt is running"
                )
            updated = _run_state(
                run,
                state="waiting",
                at=now,
                wait_condition=condition,
            )
            self._store.replace_run_in_transaction(
                connection,
                updated,
                expected_revision=expected_revision,
            )
            self._store.delete_lease_in_transaction(
                connection,
                procedure_run_id,
                token=token,
            )
            return updated

    def _wake(
        self,
        procedure_run_id: str,
        *,
        expected_revision: int,
        condition: ProcedureWaitCondition,
    ) -> ProcedureRun:
        """Make a waiting procedure ready after its exact condition is observed."""

        now = self._now()
        with (
            _translate_store_errors(),
            self._store.write_transaction() as connection,
        ):
            run = self._store.read_run_in_transaction(connection, procedure_run_id)
            if run.state == "ready":
                return run
            self._require_revision(run, expected_revision)
            if run.state != "waiting" or run.wait_condition != condition:
                raise AutomationConflict(
                    "procedure wake does not match its durable wait condition"
                )
            updated = _run_state(run, state="ready", at=now)
            self._store.replace_run_in_transaction(
                connection,
                updated,
                expected_revision=expected_revision,
            )
            return updated

    def _close(
        self,
        procedure_run_id: str,
        *,
        token: str,
        expected_revision: int,
        status: ProcedureCloseStatus,
        reason: str | None = None,
    ) -> ProcedureRun:
        """Close a leased procedure and invalidate its worker lease."""

        now = self._now()
        closure = ProcedureClosure(status=status, closed_at=now, reason=reason)
        with (
            _translate_store_errors(),
            self._store.write_transaction() as connection,
        ):
            run = self._store.read_run_in_transaction(connection, procedure_run_id)
            if run.state == "closed":
                if (
                    run.closure is not None
                    and run.closure.status == status
                    and run.closure.reason == reason
                ):
                    return run
                raise AutomationConflict(
                    "procedure run is already closed with a different result"
                )
            self._require_revision(run, expected_revision)
            if run.state != "leased":
                raise AutomationConflict("only a leased procedure can close")
            self._require_live_lease(
                connection,
                procedure_run_id,
                token,
                now,
            )
            if (
                self._store.running_step_attempt_in_transaction(
                    connection,
                    procedure_run_id,
                )
                is not None
            ):
                raise AutomationConflict(
                    "procedure cannot close while a step attempt is running"
                )
            updated = _run_state(
                run,
                state="closed",
                at=now,
                closure=closure,
            )
            self._store.replace_run_in_transaction(
                connection,
                updated,
                expected_revision=expected_revision,
            )
            self._store.delete_lease_in_transaction(
                connection,
                procedure_run_id,
                token=token,
            )
            return updated

    def _leased_run(
        self,
        connection: sqlite3.Connection,
        procedure_run_id: str,
        *,
        token: str,
        at: datetime,
    ) -> ProcedureRun:
        run = self._store.read_run_in_transaction(connection, procedure_run_id)
        if run.state != "leased":
            raise AutomationConflict("procedure worker effects require a leased run")
        self._require_live_lease(connection, procedure_run_id, token, at)
        return run

    def _require_live_lease(
        self,
        connection: sqlite3.Connection,
        procedure_run_id: str,
        token: str,
        at: datetime,
    ) -> ProcedureLeaseRecord:
        lease = self._store.read_lease_in_transaction(connection, procedure_run_id)
        if lease is None or lease.token != token or lease.expires_at <= at:
            raise AutomationConflict("procedure lease is absent, stale, or expired")
        return lease

    @staticmethod
    def _require_revision(run: ProcedureRun, expected_revision: int) -> None:
        if run.revision != expected_revision:
            raise AutomationConflict("procedure run revision changed")

    @staticmethod
    def _require_attempt_revision(
        attempt: ProcedureStepAttempt,
        expected_revision: int,
    ) -> None:
        if attempt.revision != expected_revision:
            raise AutomationConflict("procedure step revision changed")

    def _wire_lease(self, lease: ProcedureLeaseRecord) -> ProcedureWorkerLease:
        return ProcedureWorkerLease(
            procedure_run_id=lease.procedure_run_id,
            worker_id=lease.worker_id,
            lease_token=lease.token,
            issued_at=lease.acquired_at,
            renewed_at=lease.renewed_at,
            expires_at=lease.expires_at,
            heartbeat_interval_seconds=self._lease_ttl.total_seconds() / 3,
        )

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("procedure clock must return a timezone-aware datetime")
        return now


def _run_state(
    run: ProcedureRun,
    *,
    state: ProcedureRunState,
    at: datetime,
    wait_condition: ProcedureWaitCondition | None = None,
    attention_reason: str | None = None,
    closure: ProcedureClosure | None = None,
) -> ProcedureRun:
    return ProcedureRun.model_validate(
        {
            **run.model_dump(),
            "revision": run.revision + 1,
            "state": state,
            "updated_at": at,
            "wait_condition": wait_condition,
            "attention_reason": attention_reason,
            "closure": closure,
        }
    )


def _attempt_state(
    attempt: ProcedureStepAttempt,
    *,
    state: ProcedureStepAttemptState,
    at: datetime,
    output: ProcedureStepOutputRef | None = None,
    failure_reason: str | None = None,
    attention_reason: str | None = None,
) -> ProcedureStepAttempt:
    return ProcedureStepAttempt.model_validate(
        {
            **attempt.model_dump(),
            "revision": attempt.revision + 1,
            "state": state,
            "updated_at": at,
            "finished_at": at if state in {"succeeded", "failed"} else None,
            "output": output,
            "failure_reason": failure_reason,
            "attention_reason": attention_reason,
        }
    )


@contextmanager
def _translate_store_errors() -> Generator[None]:
    try:
        yield
    except AutomationNotFound as error:
        raise BackendNotFound(str(error)) from error
    except AutomationConflict as error:
        raise BackendConflict(str(error)) from error


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "AutomationService",
    "ProcedureStepTransition",
]

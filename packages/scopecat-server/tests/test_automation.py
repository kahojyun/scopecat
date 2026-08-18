from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from scopecat.automation import (
    ProcedureCloseCommand,
    ProcedureDefinitionRef,
    ProcedureRunAttentionCommand,
    ProcedureRunListQuery,
    ProcedureStepAttemptListQuery,
    ProcedureStepAttentionCommand,
    ProcedureStepBeginCommand,
    ProcedureStepCompleteCommand,
    ProcedureStepFailCommand,
    ProcedureSubmitCommand,
    ProcedureWaitCommand,
    ProcedureWorkerLeaseAcquireCommand,
    ProcedureWorkerLeaseHeartbeatCommand,
    ProcedureWorkerLeaseReleaseCommand,
    RunOutputRef,
    RunTerminalWait,
)

from scopecat_server import BackendConflict, LocalDaemonRuntime
from scopecat_server.services.automation import AutomationService
from scopecat_server.storage.sqlite.automation import SQLiteAutomationStore
from scopecat_server.storage.sqlite.connection import SQLiteDatabase
from scopecat_server.storage.sqlite.project_store import SQLiteProjectStore

_START = datetime(2026, 8, 18, 9, tzinfo=UTC)
_DEFINITION_HASH = "sha256:" + "1" * 64
_STEP_HASH = "sha256:" + "2" * 64
_OTHER_STEP_HASH = "sha256:" + "3" * 64


def _definition() -> ProcedureDefinitionRef:
    return ProcedureDefinitionRef(
        id="drag-calibration",
        version="1",
        fingerprint=_DEFINITION_HASH,
    )


def _service(
    tmp_path: Path,
) -> tuple[AutomationService, list[datetime]]:
    sqlite = SQLiteDatabase(tmp_path / "control.sqlite3")
    SQLiteProjectStore(sqlite, tmp_path / "objects").bootstrap()
    now = [_START]
    return (
        AutomationService(
            SQLiteAutomationStore(sqlite),
            lease_ttl=timedelta(seconds=30),
            clock=lambda: now[0],
        ),
        now,
    )


def _submit(service: AutomationService, *, key: str = "request-1"):
    return service.submit(
        ProcedureSubmitCommand(
            request_key=key,
            definition=_definition(),
            intent={"qubits": ["q0"]},
        )
    ).run


def test_procedure_submission_is_idempotent_and_bounded(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    first = _submit(service)

    assert _submit(service) == first
    with pytest.raises(BackendConflict, match="different intent"):
        service.submit(
            ProcedureSubmitCommand(
                request_key="request-1",
                definition=_definition(),
                intent={"qubits": ["q1"]},
            )
        )

    second = _submit(service, key="request-2")
    page = service.list(ProcedureRunListQuery(limit=1))
    assert page.items == (second,)
    assert page.next_cursor is not None
    assert service.list(
        ProcedureRunListQuery(limit=1, cursor=page.next_cursor)
    ).items == (first,)


def test_runtime_reopens_durable_procedure_state(tmp_path: Path) -> None:
    command = ProcedureSubmitCommand(
        request_key="restart-request",
        definition=_definition(),
        intent={"qubits": ["q0", "q1"]},
    )
    with LocalDaemonRuntime(tmp_path) as runtime:
        admitted = runtime.application.automation.submit(command).run

    with LocalDaemonRuntime(tmp_path) as reopened:
        assert (
            reopened.application.automation.get(admitted.procedure_run_id) == admitted
        )


def test_worker_completes_exact_step_and_closes_procedure(tmp_path: Path) -> None:
    service, now = _service(tmp_path)
    admitted = _submit(service)
    acquired = service.acquire_lease(
        ProcedureWorkerLeaseAcquireCommand(
            procedure_run_id=admitted.procedure_run_id,
            worker_id="worker-1",
            expected_run_revision=admitted.revision,
        )
    )
    assert acquired.run.revision == 2

    now[0] += timedelta(seconds=5)
    heartbeat = service.heartbeat_lease(
        ProcedureWorkerLeaseHeartbeatCommand(
            procedure_run_id=admitted.procedure_run_id,
            lease_token=acquired.lease.lease_token,
        )
    )
    assert heartbeat.run.revision == acquired.run.revision
    assert heartbeat.lease.expires_at == now[0] + timedelta(seconds=30)

    begin_command = ProcedureStepBeginCommand(
        procedure_run_id=admitted.procedure_run_id,
        lease_token=acquired.lease.lease_token,
        expected_run_revision=acquired.run.revision,
        step_key="baseline",
        operation="run",
        intent_hash=_STEP_HASH,
    )
    begun = service.begin_step(begin_command)
    assert begun.run.revision == 3
    assert begun.step.revision == 1
    assert service.begin_step(begin_command) == begun

    with pytest.raises(BackendConflict, match="different intent"):
        service.begin_step(
            begin_command.model_copy(update={"intent_hash": _OTHER_STEP_HASH})
        )

    output = RunOutputRef(run_id="run-baseline")
    complete_command = ProcedureStepCompleteCommand(
        procedure_run_id=admitted.procedure_run_id,
        lease_token=acquired.lease.lease_token,
        expected_run_revision=begun.run.revision,
        step_key=begun.step.step_key,
        attempt=begun.step.attempt,
        expected_step_revision=begun.step.revision,
        output=output,
    )
    completed = service.complete_step(complete_command)
    assert completed.run.revision == 4
    assert completed.step.state == "succeeded"
    assert completed.step.output == output
    assert service.complete_step(complete_command) == completed

    attempts = service.step_attempts(
        admitted.procedure_run_id,
        ProcedureStepAttemptListQuery(limit=1),
    )
    assert attempts.items == (completed.step,)

    closed = service.close(
        ProcedureCloseCommand(
            procedure_run_id=admitted.procedure_run_id,
            lease_token=acquired.lease.lease_token,
            expected_run_revision=completed.run.revision,
            status="succeeded",
        )
    ).run
    assert closed.state == "closed"
    assert closed.revision == 5


def test_expired_lease_takeover_reuses_running_attempt_and_fences_old_worker(
    tmp_path: Path,
) -> None:
    service, now = _service(tmp_path)
    admitted = _submit(service)
    first = service.acquire_lease(
        ProcedureWorkerLeaseAcquireCommand(
            procedure_run_id=admitted.procedure_run_id,
            worker_id="worker-1",
            expected_run_revision=1,
        )
    )
    begun = service.begin_step(
        ProcedureStepBeginCommand(
            procedure_run_id=admitted.procedure_run_id,
            lease_token=first.lease.lease_token,
            expected_run_revision=first.run.revision,
            step_key="baseline",
            operation="run",
            intent_hash=_STEP_HASH,
        )
    )

    now[0] += timedelta(seconds=31)
    takeover = service.acquire_lease(
        ProcedureWorkerLeaseAcquireCommand(
            procedure_run_id=admitted.procedure_run_id,
            worker_id="worker-2",
            expected_run_revision=begun.run.revision,
        )
    )
    assert takeover.run.revision == begun.run.revision + 1
    replay = service.begin_step(
        ProcedureStepBeginCommand(
            procedure_run_id=admitted.procedure_run_id,
            lease_token=takeover.lease.lease_token,
            expected_run_revision=takeover.run.revision,
            step_key="baseline",
            operation="run",
            intent_hash=_STEP_HASH,
        )
    )
    assert replay.step == begun.step

    with pytest.raises(BackendConflict, match="stale"):
        service.fail_step(
            ProcedureStepFailCommand(
                procedure_run_id=admitted.procedure_run_id,
                lease_token=first.lease.lease_token,
                expected_run_revision=takeover.run.revision,
                step_key="baseline",
                attempt=1,
                expected_step_revision=1,
                reason="worker lost",
            )
        )

    failed = service.fail_step(
        ProcedureStepFailCommand(
            procedure_run_id=admitted.procedure_run_id,
            lease_token=takeover.lease.lease_token,
            expected_run_revision=takeover.run.revision,
            step_key="baseline",
            attempt=1,
            expected_step_revision=1,
            reason="known failure",
        )
    )
    assert failed.run.state == "leased"
    assert failed.step.state == "failed"


def test_wait_release_and_attention_transitions_invalidate_lease(
    tmp_path: Path,
) -> None:
    service, _ = _service(tmp_path)

    waiting_run = _submit(service, key="wait")
    waiting_lease = service.acquire_lease(
        ProcedureWorkerLeaseAcquireCommand(
            procedure_run_id=waiting_run.procedure_run_id,
            worker_id="worker-wait",
            expected_run_revision=1,
        )
    )
    waiting = service.wait(
        ProcedureWaitCommand(
            procedure_run_id=waiting_run.procedure_run_id,
            lease_token=waiting_lease.lease.lease_token,
            expected_run_revision=waiting_lease.run.revision,
            condition=RunTerminalWait(run_id="run-child"),
        )
    ).run
    assert waiting.state == "waiting"
    with pytest.raises(BackendConflict, match="leased"):
        service.heartbeat_lease(
            ProcedureWorkerLeaseHeartbeatCommand(
                procedure_run_id=waiting.procedure_run_id,
                lease_token=waiting_lease.lease.lease_token,
            )
        )

    released_run = _submit(service, key="release")
    released_lease = service.acquire_lease(
        ProcedureWorkerLeaseAcquireCommand(
            procedure_run_id=released_run.procedure_run_id,
            worker_id="worker-release",
            expected_run_revision=1,
        )
    )
    released = service.release_lease(
        ProcedureWorkerLeaseReleaseCommand(
            procedure_run_id=released_run.procedure_run_id,
            lease_token=released_lease.lease.lease_token,
            expected_run_revision=released_lease.run.revision,
        )
    ).run
    assert released.state == "ready"

    run_attention = _submit(service, key="run-attention")
    run_lease = service.acquire_lease(
        ProcedureWorkerLeaseAcquireCommand(
            procedure_run_id=run_attention.procedure_run_id,
            worker_id="worker-attention",
            expected_run_revision=1,
        )
    )
    attention = service.require_run_attention(
        ProcedureRunAttentionCommand(
            procedure_run_id=run_attention.procedure_run_id,
            lease_token=run_lease.lease.lease_token,
            expected_run_revision=run_lease.run.revision,
            reason="definition cannot be loaded",
        )
    ).run
    assert attention.state == "attention_required"

    step_attention = _submit(service, key="step-attention")
    step_lease = service.acquire_lease(
        ProcedureWorkerLeaseAcquireCommand(
            procedure_run_id=step_attention.procedure_run_id,
            worker_id="worker-step-attention",
            expected_run_revision=1,
        )
    )
    begun = service.begin_step(
        ProcedureStepBeginCommand(
            procedure_run_id=step_attention.procedure_run_id,
            lease_token=step_lease.lease.lease_token,
            expected_run_revision=step_lease.run.revision,
            step_key="baseline",
            operation="run",
            intent_hash=_STEP_HASH,
        )
    )
    quarantined = service.require_step_attention(
        ProcedureStepAttentionCommand(
            procedure_run_id=step_attention.procedure_run_id,
            lease_token=step_lease.lease.lease_token,
            expected_run_revision=begun.run.revision,
            step_key=begun.step.step_key,
            attempt=begun.step.attempt,
            expected_step_revision=begun.step.revision,
            reason="indeterminate external effect",
        )
    )
    assert quarantined.run.state == "attention_required"
    assert quarantined.step.state == "attention_required"

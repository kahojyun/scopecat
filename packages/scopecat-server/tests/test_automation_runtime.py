from __future__ import annotations

from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient
from scopecat.automation import (
    ProcedureCloseCommand,
    ProcedureDefinitionRef,
    ProcedureRun,
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
from scopecat.daemon.client import DaemonClient, DaemonConflictError

from scopecat_server import LocalDaemonRuntime

_DEFINITION_HASH = "sha256:" + "1" * 64
_FIRST_STEP_HASH = "sha256:" + "2" * 64
_SECOND_STEP_HASH = "sha256:" + "3" * 64


def _definition() -> ProcedureDefinitionRef:
    return ProcedureDefinitionRef(
        id="drag-calibration",
        version="1",
        fingerprint=_DEFINITION_HASH,
    )


def _submit(client: DaemonClient, request_key: str) -> ProcedureRun:
    return client.submit_procedure(
        ProcedureSubmitCommand(
            request_key=request_key,
            definition=_definition(),
            intent={"qubits": ["q0", "q1"]},
        )
    ).run


def test_procedure_http_round_trip_persists_pages_and_fences(
    tmp_path: Path,
) -> None:
    with (
        LocalDaemonRuntime(tmp_path) as runtime,
        TestClient(runtime.app()) as transport,
        _daemon_client(transport) as client,
    ):
        first = _submit(client, "request-1")
        second = _submit(client, "request-2")
        third = _submit(client, "request-3")

        assert _submit(client, "request-1") == first
        with pytest.raises(DaemonConflictError, match="different intent"):
            client.submit_procedure(
                ProcedureSubmitCommand(
                    request_key="request-1",
                    definition=_definition(),
                    intent={"qubits": ["q2"]},
                )
            )

        page = client.list_procedures(ProcedureRunListQuery(limit=2))
        assert page.items == (third, second)
        assert page.next_cursor is not None
        assert client.list_procedures(
            ProcedureRunListQuery(limit=2, cursor=page.next_cursor)
        ).items == (first,)

        acquired = client.acquire_procedure_worker_lease(
            ProcedureWorkerLeaseAcquireCommand(
                procedure_run_id=first.procedure_run_id,
                worker_id="worker-1",
                expected_run_revision=first.revision,
            )
        )
        stale_token = f"{acquired.lease.lease_token}-stale"
        with pytest.raises(DaemonConflictError, match="stale"):
            client.heartbeat_procedure_worker_lease(
                ProcedureWorkerLeaseHeartbeatCommand(
                    procedure_run_id=first.procedure_run_id,
                    lease_token=stale_token,
                )
            )
        heartbeat = client.heartbeat_procedure_worker_lease(
            ProcedureWorkerLeaseHeartbeatCommand(
                procedure_run_id=first.procedure_run_id,
                lease_token=acquired.lease.lease_token,
            )
        )
        assert heartbeat.run.revision == acquired.run.revision

        begun = client.begin_procedure_step(
            ProcedureStepBeginCommand(
                procedure_run_id=first.procedure_run_id,
                lease_token=acquired.lease.lease_token,
                expected_run_revision=heartbeat.run.revision,
                step_key="baseline/beta",
                operation="run",
                intent_hash=_FIRST_STEP_HASH,
            )
        )
        assert begun.operation_id.startswith("procedure-step:")
        with pytest.raises(DaemonConflictError, match="stale"):
            client.complete_procedure_step(
                ProcedureStepCompleteCommand(
                    procedure_run_id=first.procedure_run_id,
                    lease_token=stale_token,
                    expected_run_revision=begun.run.revision,
                    step_key=begun.step.step_key,
                    attempt=begun.step.attempt,
                    expected_step_revision=begun.step.revision,
                    output=RunOutputRef(run_id="run-baseline"),
                )
            )
        first_output = RunOutputRef(run_id="run-baseline")
        completed = client.complete_procedure_step(
            ProcedureStepCompleteCommand(
                procedure_run_id=first.procedure_run_id,
                lease_token=acquired.lease.lease_token,
                expected_run_revision=begun.run.revision,
                step_key=begun.step.step_key,
                attempt=begun.step.attempt,
                expected_step_revision=begun.step.revision,
                output=first_output,
            )
        )

        second_begun = client.begin_procedure_step(
            ProcedureStepBeginCommand(
                procedure_run_id=first.procedure_run_id,
                lease_token=acquired.lease.lease_token,
                expected_run_revision=completed.run.revision,
                step_key="validation",
                operation="run",
                intent_hash=_SECOND_STEP_HASH,
                inputs=(first_output,),
            )
        )
        second_completed = client.complete_procedure_step(
            ProcedureStepCompleteCommand(
                procedure_run_id=first.procedure_run_id,
                lease_token=acquired.lease.lease_token,
                expected_run_revision=second_begun.run.revision,
                step_key=second_begun.step.step_key,
                attempt=second_begun.step.attempt,
                expected_step_revision=second_begun.step.revision,
                output=RunOutputRef(run_id="run-validation"),
            )
        )
        step_page = client.list_procedure_step_attempts(
            first.procedure_run_id,
            ProcedureStepAttemptListQuery(limit=1),
        )
        assert step_page.items == (second_completed.step,)
        assert step_page.next_cursor is not None
        assert client.list_procedure_step_attempts(
            first.procedure_run_id,
            ProcedureStepAttemptListQuery(limit=1, cursor=step_page.next_cursor),
        ).items == (completed.step,)

        closed = client.close_procedure(
            ProcedureCloseCommand(
                procedure_run_id=first.procedure_run_id,
                lease_token=acquired.lease.lease_token,
                expected_run_revision=second_completed.run.revision,
                status="succeeded",
            )
        ).run
        assert closed.state == "closed"
        assert client.list_procedures(ProcedureRunListQuery(state="closed")).items == (
            closed,
        )

    with (
        LocalDaemonRuntime(tmp_path) as restarted,
        TestClient(restarted.app()) as transport,
        _daemon_client(transport) as client,
    ):
        assert client.get_procedure(first.procedure_run_id) == closed
        attempts = client.list_procedure_step_attempts(
            first.procedure_run_id,
            ProcedureStepAttemptListQuery(),
        )
        assert attempts.items == (second_completed.step, completed.step)
        with pytest.raises(DaemonConflictError, match="leased"):
            client.heartbeat_procedure_worker_lease(
                ProcedureWorkerLeaseHeartbeatCommand(
                    procedure_run_id=first.procedure_run_id,
                    lease_token=acquired.lease.lease_token,
                )
            )


def test_procedure_http_exposes_worker_state_transitions(tmp_path: Path) -> None:
    with (
        LocalDaemonRuntime(tmp_path) as runtime,
        TestClient(runtime.app()) as transport,
        _daemon_client(transport) as client,
    ):
        released_run = _submit(client, "release")
        released_lease = client.acquire_procedure_worker_lease(
            ProcedureWorkerLeaseAcquireCommand(
                procedure_run_id=released_run.procedure_run_id,
                worker_id="release-worker",
                expected_run_revision=released_run.revision,
            )
        )
        released = client.release_procedure_worker_lease(
            ProcedureWorkerLeaseReleaseCommand(
                procedure_run_id=released_run.procedure_run_id,
                lease_token=released_lease.lease.lease_token,
                expected_run_revision=released_lease.run.revision,
            )
        ).run
        assert released.state == "ready"

        waiting_run = _submit(client, "wait")
        waiting_lease = client.acquire_procedure_worker_lease(
            ProcedureWorkerLeaseAcquireCommand(
                procedure_run_id=waiting_run.procedure_run_id,
                worker_id="waiting-worker",
                expected_run_revision=waiting_run.revision,
            )
        )
        waiting = client.wait_procedure(
            ProcedureWaitCommand(
                procedure_run_id=waiting_run.procedure_run_id,
                lease_token=waiting_lease.lease.lease_token,
                expected_run_revision=waiting_lease.run.revision,
                condition=RunTerminalWait(run_id="child-run"),
            )
        ).run
        assert waiting.state == "waiting"

        run_attention = _submit(client, "run-attention")
        run_attention_lease = client.acquire_procedure_worker_lease(
            ProcedureWorkerLeaseAcquireCommand(
                procedure_run_id=run_attention.procedure_run_id,
                worker_id="run-attention-worker",
                expected_run_revision=run_attention.revision,
            )
        )
        attention = client.require_procedure_run_attention(
            ProcedureRunAttentionCommand(
                procedure_run_id=run_attention.procedure_run_id,
                lease_token=run_attention_lease.lease.lease_token,
                expected_run_revision=run_attention_lease.run.revision,
                reason="definition cannot be loaded",
            )
        ).run
        assert attention.state == "attention_required"

        failed_run = _submit(client, "failed-step")
        failed_lease = client.acquire_procedure_worker_lease(
            ProcedureWorkerLeaseAcquireCommand(
                procedure_run_id=failed_run.procedure_run_id,
                worker_id="failure-worker",
                expected_run_revision=failed_run.revision,
            )
        )
        failed_begun = client.begin_procedure_step(
            ProcedureStepBeginCommand(
                procedure_run_id=failed_run.procedure_run_id,
                lease_token=failed_lease.lease.lease_token,
                expected_run_revision=failed_lease.run.revision,
                step_key="analysis",
                operation="run",
                intent_hash=_FIRST_STEP_HASH,
            )
        )
        failed = client.fail_procedure_step(
            ProcedureStepFailCommand(
                procedure_run_id=failed_run.procedure_run_id,
                lease_token=failed_lease.lease.lease_token,
                expected_run_revision=failed_begun.run.revision,
                step_key=failed_begun.step.step_key,
                attempt=failed_begun.step.attempt,
                expected_step_revision=failed_begun.step.revision,
                reason="known analysis failure",
            )
        )
        assert failed.run.state == "leased"
        assert failed.step.state == "failed"
        assert (
            client.close_procedure(
                ProcedureCloseCommand(
                    procedure_run_id=failed_run.procedure_run_id,
                    lease_token=failed_lease.lease.lease_token,
                    expected_run_revision=failed.run.revision,
                    status="failed",
                    reason="known analysis failure",
                )
            ).run.state
            == "closed"
        )

        quarantined_run = _submit(client, "step-attention")
        quarantined_lease = client.acquire_procedure_worker_lease(
            ProcedureWorkerLeaseAcquireCommand(
                procedure_run_id=quarantined_run.procedure_run_id,
                worker_id="step-attention-worker",
                expected_run_revision=quarantined_run.revision,
            )
        )
        quarantined_begun = client.begin_procedure_step(
            ProcedureStepBeginCommand(
                procedure_run_id=quarantined_run.procedure_run_id,
                lease_token=quarantined_lease.lease.lease_token,
                expected_run_revision=quarantined_lease.run.revision,
                step_key="indeterminate-child",
                operation="run",
                intent_hash=_SECOND_STEP_HASH,
            )
        )
        quarantined = client.require_procedure_step_attention(
            ProcedureStepAttentionCommand(
                procedure_run_id=quarantined_run.procedure_run_id,
                lease_token=quarantined_lease.lease.lease_token,
                expected_run_revision=quarantined_begun.run.revision,
                step_key=quarantined_begun.step.step_key,
                attempt=quarantined_begun.step.attempt,
                expected_step_revision=quarantined_begun.step.revision,
                reason="child outcome is unknown",
            )
        )
        assert quarantined.run.state == "attention_required"
        assert quarantined.step.state == "attention_required"


def _daemon_client(transport: TestClient) -> DaemonClient:
    def send(request: httpx2.Request) -> httpx2.Response:
        response = transport.request(
            request.method,
            request.url.raw_path.decode(),
            content=request.content,
            headers=dict(request.headers),
        )
        return httpx2.Response(
            response.status_code,
            content=response.content,
            headers=dict(response.headers),
        )

    return DaemonClient(
        "http://testserver",
        transport=httpx2.MockTransport(send),
    )

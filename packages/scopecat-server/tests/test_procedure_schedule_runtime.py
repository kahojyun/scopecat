from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx2
from fastapi.testclient import TestClient
from scopecat.automation import (
    ProcedureDefinitionRef,
    ProcedureRunnableQuery,
    ProcedureScheduleCancelCommand,
    ProcedureScheduleCreateCommand,
    ProcedureScheduleDueQuery,
    ProcedureScheduleListQuery,
    ProcedureScheduleMaterializeCommand,
)
from scopecat.daemon.client import DaemonClient

from scopecat_server import LocalDaemonRuntime

_HASH = "sha256:" + "1" * 64
_PAST = datetime(2020, 1, 1, tzinfo=UTC)


def _definition() -> ProcedureDefinitionRef:
    return ProcedureDefinitionRef(
        id="runtime-scheduled-procedure",
        version="1",
        fingerprint=_HASH,
    )


def test_runtime_exposes_persistent_quoted_schedules_and_runnable_runs(
    tmp_path: Path,
) -> None:
    schedule_id = "nightly/q0"
    command = ProcedureScheduleCreateCommand(
        schedule_id=schedule_id,
        definition=_definition(),
        intent={"qubits": ["q0"]},
        due_at=_PAST,
    )
    materialize = ProcedureScheduleMaterializeCommand(
        schedule_id=schedule_id,
        expected_schedule_revision=1,
    )
    with (
        LocalDaemonRuntime(tmp_path) as runtime,
        TestClient(runtime.app()) as transport,
        _daemon_client(transport) as client,
    ):
        pending = client.create_procedure_schedule(command).schedule
        assert client.get_procedure_schedule(schedule_id) == pending
        assert client.list_procedure_schedules(ProcedureScheduleListQuery()).items == (
            pending,
        )
        assert client.list_due_procedure_schedules(
            ProcedureScheduleDueQuery()
        ).items == (pending,)

        terminal = client.materialize_procedure_schedule(materialize).schedule
        assert terminal.materialization is not None
        run = client.get_procedure(terminal.materialization.procedure_run_id)
        assert client.list_runnable_procedures(
            ProcedureRunnableQuery(definitions=(_definition(),))
        ).items == (run,)

    with (
        LocalDaemonRuntime(tmp_path) as reopened,
        TestClient(reopened.app()) as transport,
        _daemon_client(transport) as client,
    ):
        assert client.get_procedure_schedule(schedule_id) == terminal
        assert client.materialize_procedure_schedule(materialize).schedule == terminal
        assert client.get_procedure(run.procedure_run_id) == run


def test_runtime_cancel_route_persists_terminal_schedule(tmp_path: Path) -> None:
    command = ProcedureScheduleCreateCommand(
        schedule_id="maintenance/q1",
        definition=_definition(),
        intent={"qubits": ["q1"]},
        due_at=datetime(2100, 1, 1, tzinfo=UTC),
    )
    with (
        LocalDaemonRuntime(tmp_path) as runtime,
        TestClient(runtime.app()) as transport,
        _daemon_client(transport) as client,
    ):
        pending = client.create_procedure_schedule(command).schedule
        cancelled = client.cancel_procedure_schedule(
            ProcedureScheduleCancelCommand(
                schedule_id=pending.schedule_id,
                expected_schedule_revision=pending.revision,
                actor="operator",
                reason="maintenance window",
            )
        ).schedule
        assert cancelled.state == "cancelled"
        assert client.create_procedure_schedule(command).schedule == cancelled


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

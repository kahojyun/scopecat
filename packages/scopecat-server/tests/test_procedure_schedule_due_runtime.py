from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from scopecat.automation import (
    ProcedureDefinitionRef,
    ProcedureSchedule,
    ProcedureScheduleCreateCommand,
    ProcedureScheduleCreateReceipt,
    ProcedureScheduleDuePage,
)

from scopecat_server import LocalDaemonRuntime

_DUE = datetime(2020, 1, 1, tzinfo=UTC)
_HASH = "sha256:" + "1" * 64


def test_due_route_keyset_advances_past_unchanged_pending_schedule(
    tmp_path: Path,
) -> None:
    definition = ProcedureDefinitionRef(
        id="runtime-due-keyset",
        version="1",
        fingerprint=_HASH,
    )
    first_command = ProcedureScheduleCreateCommand(
        schedule_id="poison",
        definition=definition,
        intent={"slot": 1},
        due_at=_DUE + timedelta(minutes=1),
    )
    second_command = ProcedureScheduleCreateCommand(
        schedule_id="later-inserted",
        definition=definition,
        intent={"slot": 2},
        due_at=_DUE,
    )
    with LocalDaemonRuntime(tmp_path) as runtime, TestClient(runtime.app()) as client:
        first = _create(client, first_command)
        second = _create(client, second_command)

        first_page = ProcedureScheduleDuePage.model_validate(
            client.get(
                "/api/v1/procedure-schedules/due",
                params={"limit": 1},
            ).json()
        )
        assert first_page.items == (first,)
        assert first_page.next_cursor is not None
        assert first_page.through_sequence is not None
        second_page = ProcedureScheduleDuePage.model_validate(
            client.get(
                "/api/v1/procedure-schedules/due",
                params={
                    "limit": 1,
                    "cursor": first_page.next_cursor,
                    "through_sequence": first_page.through_sequence,
                },
            ).json()
        )
        assert second_page.items == (second,)
        assert second_page.next_cursor is None
        assert second_page.through_sequence is None
        assert (
            client.get(
                "/api/v1/procedure-schedules/due",
                params={"cursor": 1},
            ).status_code
            == 422
        )


def _create(
    client: TestClient,
    command: ProcedureScheduleCreateCommand,
) -> ProcedureSchedule:
    response = client.post(
        "/api/v1/procedure-schedules",
        json=command.model_dump(mode="json"),
    )
    response.raise_for_status()
    return ProcedureScheduleCreateReceipt.model_validate(response.json()).schedule

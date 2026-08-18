from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from scopecat.automation import (
    ProcedureDefinitionRef,
    ProcedureSchedule,
    ProcedureScheduleCancellation,
    procedure_intent_hash,
)

from scopecat_server.storage.sqlite.connection import SQLiteDatabase
from scopecat_server.storage.sqlite.procedure_schedules import (
    SQLiteProcedureScheduleStore,
)
from scopecat_server.storage.sqlite.project_store import SQLiteProjectStore

_START = datetime(2026, 8, 18, 9, tzinfo=UTC)
_HASH = "sha256:" + "1" * 64


def _store(tmp_path: Path) -> SQLiteProcedureScheduleStore:
    sqlite = SQLiteDatabase(tmp_path / "control.sqlite3")
    SQLiteProjectStore(sqlite, tmp_path / "objects").bootstrap()
    return SQLiteProcedureScheduleStore(sqlite)


def _schedule(schedule_id: str, *, due_at: datetime) -> ProcedureSchedule:
    definition = ProcedureDefinitionRef(
        id="drag-calibration",
        version="1",
        fingerprint=_HASH,
    )
    intent = {"qubits": [schedule_id]}
    return ProcedureSchedule(
        schedule_id=schedule_id,
        definition=definition,
        intent=intent,
        intent_hash=procedure_intent_hash(definition, intent),
        due_at=due_at,
        revision=1,
        state="pending",
        created_at=_START,
        updated_at=_START,
    )


def test_store_round_trips_pages_and_due_schedules_with_canonical_time(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    later = _schedule("later", due_at=_START + timedelta(minutes=2))
    earlier = _schedule("earlier", due_at=_START + timedelta(minutes=1))
    future = _schedule("future", due_at=_START + timedelta(hours=1))
    with store.write_transaction() as connection:
        for schedule in (later, earlier, future):
            store.insert_in_transaction(connection, schedule)

    newest = store.list(limit=1)
    assert newest.items == (future,)
    assert newest.next_cursor is not None
    assert store.list(limit=2, before=newest.next_cursor).items == (earlier, later)

    offset_now = (_START + timedelta(minutes=3)).astimezone(
        timezone(timedelta(hours=8))
    )
    first_due = store.due(at=offset_now, limit=1)
    assert first_due.items == (earlier,)
    assert first_due.has_more is True
    assert store.due(at=offset_now, limit=10).items == (earlier, later)

    cancelled_at = _START + timedelta(minutes=4)
    cancelled = earlier.model_copy(
        update={
            "revision": 2,
            "state": "cancelled",
            "updated_at": cancelled_at,
            "cancellation": ProcedureScheduleCancellation(
                actor="operator",
                reason="maintenance",
                cancelled_at=cancelled_at,
            ),
        }
    )
    with store.write_transaction() as connection:
        store.replace_in_transaction(connection, cancelled, expected_revision=1)
    assert store.read(earlier.schedule_id) == cancelled
    assert store.list(state="cancelled").items == (cancelled,)
    assert store.due(at=offset_now + timedelta(hours=1)).items == (later, future)

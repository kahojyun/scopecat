from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import JsonValue, ValidationError
from scopecat_testkit.records import assert_model_round_trip

from scopecat.automation import (
    ProcedureDefinitionRef,
    ProcedureRun,
    ProcedureRunnablePage,
    ProcedureRunnableQuery,
    ProcedureRunState,
    ProcedureSchedule,
    ProcedureScheduleCancelCommand,
    ProcedureScheduleCancellation,
    ProcedureScheduleCancelReceipt,
    ProcedureScheduleCreateCommand,
    ProcedureScheduleCreateReceipt,
    ProcedureScheduleDuePage,
    ProcedureScheduleDueQuery,
    ProcedureScheduleListQuery,
    ProcedureScheduleMaterialization,
    ProcedureScheduleMaterializeCommand,
    ProcedureScheduleMaterializeReceipt,
    ProcedureSchedulePage,
    RunTerminalWait,
    procedure_intent_hash,
    procedure_schedule_request_key,
)

_HASH = "sha256:" + "1" * 64
_START = datetime(2026, 8, 18, 8, tzinfo=UTC)
_DUE = _START + timedelta(hours=1)
_INTENT: dict[str, JsonValue] = {"target_ids": ["q0"]}


def _definition(*, version: str = "1") -> ProcedureDefinitionRef:
    return ProcedureDefinitionRef(
        id="drag-calibration",
        version=version,
        fingerprint=_HASH,
    )


def _pending(
    *,
    schedule_id: str = "nightly-q0",
    due_at: datetime = _DUE,
) -> ProcedureSchedule:
    definition = _definition()
    return ProcedureSchedule(
        schedule_id=schedule_id,
        definition=definition,
        intent=_INTENT,
        intent_hash=procedure_intent_hash(definition, _INTENT),
        due_at=due_at,
        revision=1,
        state="pending",
        created_at=_START,
        updated_at=_START,
    )


def _materialized() -> ProcedureSchedule:
    pending = _pending()
    return ProcedureSchedule.model_validate(
        {
            **pending.model_dump(),
            "revision": 2,
            "state": "materialized",
            "updated_at": _DUE,
            "materialization": ProcedureScheduleMaterialization(
                procedure_run_id="procedure-q0",
                request_key=procedure_schedule_request_key(
                    pending.schedule_id,
                    pending.due_at,
                    pending.definition,
                    pending.intent_hash,
                ),
                materialized_at=_DUE,
            ),
        }
    )


def _cancelled() -> ProcedureSchedule:
    pending = _pending()
    cancelled_at = _START + timedelta(minutes=1)
    return ProcedureSchedule.model_validate(
        {
            **pending.model_dump(),
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


def _run(
    state: ProcedureRunState,
    *,
    run_id: str = "procedure-q0",
) -> ProcedureRun:
    details: dict[str, object] = {}
    if state == "waiting":
        details["wait_condition"] = RunTerminalWait(run_id="run-child")
    return ProcedureRun.model_validate(
        {
            "procedure_run_id": run_id,
            "request_key": f"request-{run_id}",
            "definition": _definition(),
            "intent": _INTENT,
            "intent_hash": procedure_intent_hash(_definition(), _INTENT),
            "revision": 1,
            "state": state,
            "created_at": _START,
            "updated_at": _START,
            **details,
        }
    )


def test_create_command_canonicalizes_time_and_terminal_replay_receipt() -> None:
    offset = timezone(timedelta(hours=8))
    command = ProcedureScheduleCreateCommand(
        schedule_id="nightly-q0",
        definition=_definition(),
        intent=_INTENT,
        due_at=_DUE.astimezone(offset),
    )

    assert command.due_at == _DUE
    assert command.intent_hash == procedure_intent_hash(_definition(), _INTENT)
    assert assert_model_round_trip(command) == command
    assert ProcedureScheduleCreateReceipt(schedule=_materialized()).schedule.state == (
        "materialized"
    )


def test_schedule_pages_are_bounded_unique_and_oldest_due_first() -> None:
    first = _pending(schedule_id="first", due_at=_DUE)
    second = _pending(schedule_id="second", due_at=_DUE + timedelta(minutes=1))

    assert ProcedureScheduleListQuery(limit=200, state="pending").state == "pending"
    assert ProcedureScheduleDueQuery(limit=200).limit == 200
    assert (
        assert_model_round_trip(
            ProcedureSchedulePage(items=(second, first), next_cursor=3)
        ).next_cursor
        == 3
    )
    assert ProcedureScheduleDuePage(items=(first, second), has_more=True).has_more
    with pytest.raises(ValidationError):
        ProcedureScheduleListQuery(limit=201)
    with pytest.raises(ValidationError):
        ProcedureScheduleDueQuery(limit=201)
    with pytest.raises(ValidationError, match="ids must be unique"):
        ProcedureSchedulePage(items=(first, first))
    with pytest.raises(ValidationError, match="oldest-first"):
        ProcedureScheduleDuePage(items=(second, first))
    with pytest.raises(ValidationError, match="requires pending"):
        ProcedureScheduleDuePage(items=(_materialized(),))


def test_terminal_commands_and_receipts_require_exact_states() -> None:
    cancel = ProcedureScheduleCancelCommand(
        schedule_id="nightly-q0",
        expected_schedule_revision=1,
        actor="operator",
        reason="maintenance",
    )
    materialize = ProcedureScheduleMaterializeCommand(
        schedule_id="nightly-q0",
        expected_schedule_revision=1,
    )

    assert assert_model_round_trip(cancel) == cancel
    assert assert_model_round_trip(materialize) == materialize
    assert ProcedureScheduleCancelReceipt(schedule=_cancelled()).schedule.state == (
        "cancelled"
    )
    assert (
        ProcedureScheduleMaterializeReceipt(schedule=_materialized()).schedule.state
        == "materialized"
    )
    with pytest.raises(ValidationError, match="requires cancellation"):
        ProcedureScheduleCancelReceipt(schedule=_pending())
    with pytest.raises(ValidationError, match="requires materialization"):
        ProcedureScheduleMaterializeReceipt(schedule=_pending())
    with pytest.raises(ValidationError, match="cancellation identity"):
        ProcedureScheduleCancelCommand(
            schedule_id="nightly-q0",
            expected_schedule_revision=1,
            actor=" ",
            reason="maintenance",
        )


def test_runnable_query_is_exact_bounded_and_page_is_runnable() -> None:
    definition = _definition()
    query = ProcedureRunnableQuery(definitions=(definition,), limit=200)

    assert assert_model_round_trip(query) == query
    assert ProcedureRunnablePage(
        items=(_run("ready"), _run("leased", run_id="procedure-q1")),
        has_more=True,
    ).has_more
    with pytest.raises(ValidationError, match="definitions must be unique"):
        ProcedureRunnableQuery(definitions=(definition, definition))
    with pytest.raises(ValidationError):
        ProcedureRunnableQuery(
            definitions=tuple(_definition(version=str(i)) for i in range(201))
        )
    with pytest.raises(ValidationError, match="requires runnable states"):
        ProcedureRunnablePage(items=(_run("waiting"),))
    with pytest.raises(ValidationError, match="ids must be unique"):
        ProcedureRunnablePage(items=(_run("ready"), _run("ready")))

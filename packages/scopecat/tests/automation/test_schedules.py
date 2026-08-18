from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest
from pydantic import JsonValue, ValidationError
from scopecat_testkit.records import assert_model_round_trip

from scopecat.automation import (
    ProcedureDefinitionRef,
    ProcedureSchedule,
    ProcedureScheduleCancellation,
    ProcedureScheduleMaterialization,
    procedure_intent_hash,
    procedure_schedule_request_key,
)

_DEFINITION_HASH = "sha256:" + "1" * 64
_OTHER_HASH = "sha256:" + "2" * 64
_CREATED = datetime(2026, 8, 18, 8, tzinfo=UTC)
_DUE = _CREATED + timedelta(hours=1)
_INTENT: dict[str, JsonValue] = {"target": {"qubits": ["q0"]}}


def _definition() -> ProcedureDefinitionRef:
    return ProcedureDefinitionRef(
        id="drag-calibration",
        version="2",
        fingerprint=_DEFINITION_HASH,
    )


def _pending_schedule(*, schedule_id: str = "nightly-q0") -> ProcedureSchedule:
    definition = _definition()
    return ProcedureSchedule(
        schedule_id=schedule_id,
        definition=definition,
        intent=_INTENT,
        intent_hash=procedure_intent_hash(definition, _INTENT),
        due_at=_DUE,
        revision=1,
        state="pending",
        created_at=_CREATED,
        updated_at=_CREATED,
    )


def _materialized_schedule() -> ProcedureSchedule:
    pending = _pending_schedule()
    request_key = procedure_schedule_request_key(
        pending.schedule_id,
        pending.due_at,
        pending.definition,
        pending.intent_hash,
    )
    return pending.model_copy(
        update={
            "revision": 2,
            "state": "materialized",
            "updated_at": _DUE,
            "materialization": ProcedureScheduleMaterialization(
                procedure_run_id="procedure-nightly-q0",
                request_key=request_key,
                materialized_at=_DUE,
            ),
        }
    )


def test_schedule_canonicalizes_utc_and_freezes_exact_intent() -> None:
    offset = timezone(timedelta(hours=8))
    schedule = _pending_schedule().model_copy(
        update={"due_at": datetime(2026, 8, 18, 17, tzinfo=offset)}
    )
    restored = ProcedureSchedule.model_validate_json(schedule.model_dump_json())

    assert restored.due_at == _DUE
    assert assert_model_round_trip(restored) == restored
    target = cast("dict[str, object]", restored.intent["target"])
    with pytest.raises(TypeError):
        target["qubits"] = ["q1"]


def test_schedule_request_key_covers_exact_utc_schedule_identity() -> None:
    schedule = _pending_schedule()
    offset_due = schedule.due_at.astimezone(timezone(timedelta(hours=8)))
    key = procedure_schedule_request_key(
        schedule.schedule_id,
        schedule.due_at,
        schedule.definition,
        schedule.intent_hash,
    )

    assert key == procedure_schedule_request_key(
        schedule.schedule_id,
        offset_due,
        schedule.definition,
        schedule.intent_hash,
    )
    assert key != procedure_schedule_request_key(
        "nightly-q1",
        schedule.due_at,
        schedule.definition,
        schedule.intent_hash,
    )
    assert key != procedure_schedule_request_key(
        schedule.schedule_id,
        schedule.due_at + timedelta(seconds=1),
        schedule.definition,
        schedule.intent_hash,
    )
    assert key != procedure_schedule_request_key(
        schedule.schedule_id,
        schedule.due_at,
        schedule.definition,
        _OTHER_HASH,
    )


def test_materialized_schedule_binds_request_key_and_lifetime() -> None:
    schedule = _materialized_schedule()
    materialization = schedule.materialization

    assert materialization is not None
    assert assert_model_round_trip(schedule) == schedule
    with pytest.raises(ValidationError, match="request key must identify"):
        ProcedureSchedule.model_validate(
            {
                **schedule.model_dump(),
                "materialization": {
                    **materialization.model_dump(),
                    "request_key": "procedure-schedule:wrong",
                },
            }
        )

    pending = _pending_schedule()
    past_due = pending.model_copy(update={"due_at": _CREATED - timedelta(hours=1)})
    with pytest.raises(ValidationError, match="within its lifetime"):
        ProcedureSchedule.model_validate(
            {
                **past_due.model_dump(),
                "revision": 2,
                "state": "materialized",
                "materialization": {
                    "procedure_run_id": "procedure-nightly-q0",
                    "request_key": procedure_schedule_request_key(
                        past_due.schedule_id,
                        past_due.due_at,
                        past_due.definition,
                        past_due.intent_hash,
                    ),
                    "materialized_at": past_due.due_at,
                },
            }
        )


def test_cancelled_schedule_requires_audited_terminal_details() -> None:
    pending = _pending_schedule()
    cancelled = pending.model_copy(
        update={
            "revision": 2,
            "state": "cancelled",
            "updated_at": _CREATED + timedelta(minutes=1),
            "cancellation": ProcedureScheduleCancellation(
                actor="calibration-operator",
                reason="maintenance window",
                cancelled_at=_CREATED + timedelta(minutes=1),
            ),
        }
    )

    assert assert_model_round_trip(cancelled) == cancelled
    with pytest.raises(ValidationError, match="cancellation identity"):
        ProcedureScheduleCancellation(
            actor=" ",
            reason="maintenance window",
            cancelled_at=_CREATED,
        )
    with pytest.raises(ValidationError, match="requires cancellation"):
        ProcedureSchedule.model_validate(
            {
                **pending.model_dump(),
                "revision": 2,
                "state": "cancelled",
            }
        )


def test_schedule_rejects_naive_times_and_wrong_intent_hash() -> None:
    pending = _pending_schedule()
    with pytest.raises(ValidationError, match="UTC offset"):
        ProcedureSchedule.model_validate(
            {**pending.model_dump(), "due_at": _DUE.replace(tzinfo=None)}
        )
    with pytest.raises(ValidationError, match="must cover its definition"):
        ProcedureSchedule.model_validate(
            {**pending.model_dump(), "intent_hash": _OTHER_HASH}
        )

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx2
from pydantic import BaseModel

from scopecat.automation import (
    ProcedureDefinitionRef,
    ProcedureRun,
    ProcedureRunnablePage,
    ProcedureRunnableQuery,
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
    procedure_intent_hash,
    procedure_schedule_request_key,
)
from scopecat.daemon.client import DaemonClient

_HASH = "sha256:" + "1" * 64
_START = datetime(2026, 8, 18, 8, tzinfo=UTC)
_DUE = _START + timedelta(hours=1)
_SCHEDULE_ID = "nightly/q0?slot=1"
_INTENT = {"target_ids": ["q0"]}


def _definition() -> ProcedureDefinitionRef:
    return ProcedureDefinitionRef(
        id="drag-calibration",
        version="2",
        fingerprint=_HASH,
    )


def _pending() -> ProcedureSchedule:
    definition = _definition()
    return ProcedureSchedule(
        schedule_id=_SCHEDULE_ID,
        definition=definition,
        intent=_INTENT,
        intent_hash=procedure_intent_hash(definition, _INTENT),
        due_at=_DUE,
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


def _run() -> ProcedureRun:
    definition = _definition()
    return ProcedureRun(
        procedure_run_id="procedure-q0",
        request_key="request-q0",
        definition=definition,
        intent=_INTENT,
        intent_hash=procedure_intent_hash(definition, _INTENT),
        revision=1,
        state="ready",
        created_at=_DUE,
        updated_at=_DUE,
    )


def test_schedule_and_runnable_client_methods_use_exact_routes_and_models() -> None:
    requests: list[httpx2.Request] = []
    post_attempts: dict[str, int] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        path = request.url.path
        if path == "/api/v1/procedure-schedules" and request.method == "POST":
            ProcedureScheduleCreateCommand.model_validate_json(request.content)
            post_attempts[path] = post_attempts.get(path, 0) + 1
            if post_attempts[path] == 1:
                raise httpx2.ReadError("create response was lost", request=request)
            return _response(ProcedureScheduleCreateReceipt(schedule=_materialized()))
        if path == "/api/v1/procedure-schedules" and request.method == "GET":
            return _response(ProcedureSchedulePage(items=(_pending(),)))
        if path == "/api/v1/procedure-schedules/due":
            return _response(ProcedureScheduleDuePage(items=(_pending(),)))
        if path == f"/api/v1/procedure-schedules/by-id/{_SCHEDULE_ID}":
            return _response(_pending())
        if path == f"/api/v1/procedure-schedule-cancellations/{_SCHEDULE_ID}":
            ProcedureScheduleCancelCommand.model_validate_json(request.content)
            post_attempts[path] = post_attempts.get(path, 0) + 1
            if post_attempts[path] == 1:
                raise httpx2.ReadError("cancel response was lost", request=request)
            return _response(ProcedureScheduleCancelReceipt(schedule=_cancelled()))
        if path == f"/api/v1/procedure-schedule-materializations/{_SCHEDULE_ID}":
            ProcedureScheduleMaterializeCommand.model_validate_json(request.content)
            post_attempts[path] = post_attempts.get(path, 0) + 1
            if post_attempts[path] == 1:
                raise httpx2.ReadError(
                    "materialize response was lost",
                    request=request,
                )
            return _response(
                ProcedureScheduleMaterializeReceipt(schedule=_materialized())
            )
        if path == "/api/v1/procedures/runnable/query":
            ProcedureRunnableQuery.model_validate_json(request.content)
            return _response(ProcedureRunnablePage(items=(_run(),)))
        raise AssertionError(f"unexpected request: {request.method} {path}")

    client = DaemonClient(
        "http://daemon.local/",
        transport=httpx2.MockTransport(handler),
    )
    create = ProcedureScheduleCreateCommand(
        schedule_id=_SCHEDULE_ID,
        definition=_definition(),
        intent=_INTENT,
        due_at=_DUE,
    )
    cancel = ProcedureScheduleCancelCommand(
        schedule_id=_SCHEDULE_ID,
        expected_schedule_revision=1,
        actor="operator",
        reason="maintenance",
    )
    materialize = ProcedureScheduleMaterializeCommand(
        schedule_id=_SCHEDULE_ID,
        expected_schedule_revision=1,
    )

    assert client.create_procedure_schedule(create).schedule.state == "materialized"
    assert client.list_procedure_schedules(
        ProcedureScheduleListQuery(cursor=4, limit=5, state="pending")
    ).items == (_pending(),)
    assert client.list_due_procedure_schedules(
        ProcedureScheduleDueQuery(cursor=5, through_sequence=9, limit=6)
    ).items == (_pending(),)
    assert client.get_procedure_schedule(_SCHEDULE_ID) == _pending()
    assert client.cancel_procedure_schedule(cancel).schedule.state == "cancelled"
    assert (
        client.materialize_procedure_schedule(materialize).schedule.state
        == "materialized"
    )
    assert client.list_runnable_procedures(
        ProcedureRunnableQuery(definitions=(_definition(),), limit=7)
    ).items == (_run(),)

    assert [request.method for request in requests] == [
        "POST",
        "POST",
        "GET",
        "GET",
        "GET",
        "POST",
        "POST",
        "POST",
        "POST",
        "POST",
    ]
    assert requests[0].content == requests[1].content
    assert dict(requests[2].url.params) == {
        "limit": "5",
        "cursor": "4",
        "state": "pending",
    }
    assert dict(requests[3].url.params) == {
        "limit": "6",
        "cursor": "5",
        "through_sequence": "9",
    }
    quoted_schedule_id = b"nightly%2Fq0%3Fslot%3D1"
    assert quoted_schedule_id in requests[4].url.raw_path
    assert quoted_schedule_id in requests[5].url.raw_path
    assert quoted_schedule_id in requests[7].url.raw_path
    assert requests[5].content == requests[6].content
    assert requests[7].content == requests[8].content
    assert (
        ProcedureScheduleCancelCommand.model_validate_json(requests[5].content)
        == cancel
    )
    assert (
        ProcedureScheduleMaterializeCommand.model_validate_json(requests[7].content)
        == materialize
    )
    assert ProcedureRunnableQuery.model_validate_json(requests[9].content) == (
        ProcedureRunnableQuery(definitions=(_definition(),), limit=7)
    )


def _response(model: BaseModel) -> httpx2.Response:
    return httpx2.Response(200, json=model.model_dump(mode="json"))

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx2
from pydantic import BaseModel

from scopecat.automation import (
    CalibrationCohort,
    CalibrationCohortCreateCommand,
    CalibrationCohortCreateReceipt,
    CalibrationCohortGetReceipt,
    CalibrationCohortListQuery,
    CalibrationCohortMember,
    CalibrationCohortMemberListQuery,
    CalibrationCohortMemberPage,
    CalibrationCohortMemberSpec,
    CalibrationCohortPage,
    CalibrationCohortSpec,
    CalibrationCohortSummary,
    CalibrationConfigSourceRef,
    CalibrationDefinitionRef,
    CalibrationMissingSuccessDueReason,
    CalibrationStatus,
    CalibrationStatusQuery,
    CalibrationStatusReceipt,
    CalibrationStatusSnapshot,
    CalibrationTargetRef,
    ProcedureDefinitionRef,
    calibration_cohort_member_request_key,
    calibration_cohort_spec_hash,
    calibration_freshness_fingerprint,
    calibration_key,
)
from scopecat.daemon.client import DaemonClient

_HASH_1 = "sha256:" + "1" * 64
_HASH_2 = "sha256:" + "2" * 64
_HASH_3 = "sha256:" + "3" * 64
_OBSERVED = datetime(2026, 8, 18, 8, tzinfo=UTC)
_CREATED = _OBSERVED + timedelta(seconds=1)
_COHORT_ID = "cohort/q0?q=1"


def test_calibration_client_uses_typed_exact_routes_and_retries_create() -> None:
    cohort, member, snapshot = _fixture()
    create = CalibrationCohortCreateCommand(
        cohort_id=cohort.cohort_id,
        spec=cohort.spec,
    )
    status_query = CalibrationStatusQuery(
        calibration_keys=(member.spec.calibration_key,),
        fanout_scope=cohort.spec.fanout_scope,
    )
    requests: list[httpx2.Request] = []
    create_attempts = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal create_attempts
        requests.append(request)
        path = request.url.path
        if path == "/api/v1/calibration-status/query":
            assert CalibrationStatusQuery.model_validate_json(request.content) == (
                status_query
            )
            return _response(CalibrationStatusReceipt(snapshot=snapshot))
        if path == "/api/v1/calibration-cohorts" and request.method == "POST":
            assert (
                CalibrationCohortCreateCommand.model_validate_json(request.content)
                == create
            )
            create_attempts += 1
            if create_attempts == 1:
                raise httpx2.ReadError("create response lost", request=request)
            return _response(
                CalibrationCohortCreateReceipt(cohort=cohort, members=(member,))
            )
        if path == "/api/v1/calibration-cohorts" and request.method == "GET":
            return _response(
                CalibrationCohortPage(
                    items=(CalibrationCohortSummary.from_cohort(cohort),)
                )
            )
        if path == f"/api/v1/calibration-cohort-members/by-cohort/{_COHORT_ID}":
            return _response(
                CalibrationCohortMemberPage(
                    cohort_id=cohort.cohort_id,
                    items=(member,),
                )
            )
        if path == f"/api/v1/calibration-cohorts/by-id/{_COHORT_ID}":
            return _response(CalibrationCohortGetReceipt(cohort=cohort))
        raise AssertionError(f"unexpected request: {request.method} {path}")

    client = DaemonClient(
        "http://daemon.local/",
        transport=httpx2.MockTransport(handler),
    )

    assert client.query_calibration_status(status_query).snapshot == snapshot
    assert client.create_calibration_cohort(create).cohort == cohort
    assert client.get_calibration_cohort(_COHORT_ID).cohort == cohort
    assert client.list_calibration_cohorts(
        CalibrationCohortListQuery(
            cursor=9,
            limit=7,
            fanout_scope=cohort.spec.fanout_scope,
        )
    ).items == (CalibrationCohortSummary.from_cohort(cohort),)
    assert client.list_calibration_cohort_members(
        CalibrationCohortMemberListQuery(
            cohort_id=_COHORT_ID,
            cursor=0,
            limit=6,
        )
    ).items == (member,)

    assert [request.method for request in requests] == [
        "POST",
        "POST",
        "POST",
        "GET",
        "GET",
        "GET",
    ]
    assert requests[1].content == requests[2].content
    quoted_id = b"cohort%2Fq0%3Fq%3D1"
    assert quoted_id in requests[3].url.raw_path
    assert quoted_id in requests[5].url.raw_path
    assert dict(requests[4].url.params) == {
        "limit": "7",
        "cursor": "9",
        "fanout_scope": "chip-alpha",
    }
    assert dict(requests[5].url.params) == {"limit": "6", "cursor": "0"}


def _fixture() -> tuple[
    CalibrationCohort,
    CalibrationCohortMember,
    CalibrationStatusSnapshot,
]:
    definition = CalibrationDefinitionRef(
        id="drag",
        version="1",
        fingerprint=_HASH_1,
    )
    target = CalibrationTargetRef(kind="qubit", id="q0")
    procedure = ProcedureDefinitionRef(
        id="drag-procedure",
        version="1",
        fingerprint=_HASH_2,
    )
    key = calibration_key(definition.id, target)
    status = CalibrationStatus(calibration_key=key)
    member_spec = CalibrationCohortMemberSpec(
        member_id="q0",
        calibration_key=key,
        definition=definition,
        target=target,
        procedure=procedure,
        intent={"qubit_id": "q0"},
        input_fingerprint=_HASH_3,
        freshness_fingerprint=calibration_freshness_fingerprint(
            definition=definition,
            target=target,
            procedure=procedure,
            input_fingerprint=_HASH_3,
            dependencies=(),
        ),
        due_reasons=(CalibrationMissingSuccessDueReason(),),
    )
    spec = CalibrationCohortSpec(
        planner=definition,
        config_source=CalibrationConfigSourceRef(
            selector="active",
            entry_id="config-1",
            config_ref="configs/config-1",
            content_hash=_HASH_3,
            registry_generation=3,
        ),
        fanout_scope="chip-alpha",
        max_in_flight=2,
        observed_fanout_active_count=0,
        evaluated_at=_OBSERVED,
        observations=(status,),
        members=(member_spec,),
    )
    cohort = CalibrationCohort(
        cohort_id=_COHORT_ID,
        spec=spec,
        spec_hash=calibration_cohort_spec_hash(spec),
        created_at=_CREATED,
    )
    member = CalibrationCohortMember(
        cohort_id=cohort.cohort_id,
        index=0,
        spec=member_spec,
        procedure_run_id="procedure-q0",
        request_key=calibration_cohort_member_request_key(
            cohort.cohort_id,
            member_spec,
        ),
        admitted_at=_CREATED,
    )
    return (
        cohort,
        member,
        CalibrationStatusSnapshot(
            observed_at=_OBSERVED,
            fanout_scope=spec.fanout_scope,
            fanout_active_count=0,
            statuses=spec.observations,
        ),
    )


def _response(model: BaseModel) -> httpx2.Response:
    return httpx2.Response(200, json=model.model_dump(mode="json"))

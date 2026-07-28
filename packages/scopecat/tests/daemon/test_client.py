from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from pydantic import BaseModel

from scopecat.control.models import (
    ControlRun,
    RunAdmissionRecord,
    RunPlanSummary,
)
from scopecat.daemon.client import (
    DaemonClient,
    DaemonConflictError,
    DaemonNotFoundError,
)
from scopecat.daemon.views import RunSummary, RunSummaryPage
from scopecat.daemon.wire import (
    ExecutorLease,
    ExecutorStartRequest,
    PayloadObjectReceipt,
    RunAdmission,
    RunInstrumentProvisionCommand,
    RunInstrumentProvisionReceipt,
    RunSubmission,
)
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.records.artifact import (
    BlobPayloadBody,
    InlinePayloadBody,
    command_payload_from_bytes,
)
from scopecat.records.run import RunManifest
from scopecat.records.run_request import RunRequest
from scopecat.sdk.instruments.contracts import (
    InstrumentOperationArgument,
    InvokeCommand,
    InvokeReceipt,
)
from tests.testkit.workflow_fixtures import load_config

_NOW = datetime(2026, 7, 23, 9, tzinfo=UTC)
_HASH = f"sha256:{'a' * 64}"
_REQUEST = RunRequest(experiment_id="request-1")


def test_get_query_and_post_body_use_typed_wire_models() -> None:
    requests: list[httpx2.Request] = []
    client = _client(requests)

    runs = client.list_runs(limit=5, before=2, state="queued")
    admission = client.submit_run(_submission())

    assert isinstance(runs, RunSummaryPage)
    assert runs.items[0].manifest.run_id == admission.run_id
    assert admission.submission_id == "submission-1"

    list_request = requests[0]
    assert list_request.method == "GET"
    assert list_request.url.path == "/api/v1/runs"
    assert dict(list_request.url.params) == {
        "limit": "5",
        "before": "2",
        "state": "queued",
    }
    submit_request = requests[1]
    assert submit_request.method == "POST"
    assert submit_request.url.path == "/api/v1/runs"
    assert RunSubmission.model_validate_json(submit_request.content) == _submission()


def test_executor_start_rejects_receipt_for_another_run() -> None:
    other_lease = _lease().model_copy(update={"run_id": "run-2"})
    client = DaemonClient(
        "http://daemon.local/",
        transport=httpx2.MockTransport(lambda _request: _model(other_lease)),
    )

    with pytest.raises(ValueError, match="does not match"):
        client.start_executor(
            "run-1",
            ExecutorStartRequest(
                executor_id="notebook-1",
            ),
        )


def test_run_instrument_provision_retries_the_same_operation_after_response_loss() -> (
    None
):
    requests: list[httpx2.Request] = []
    command = RunInstrumentProvisionCommand(
        lease_id="lease-1",
        operation_id="lifecycle.provide-instruments",
    )
    receipt = RunInstrumentProvisionReceipt(
        run_id="run-1",
        operation_id=command.operation_id,
        status="ready",
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if len(requests) == 1:
            raise httpx2.ReadError("response was lost", request=request)
        return _model(receipt)

    client = DaemonClient(
        "http://daemon.local/",
        transport=httpx2.MockTransport(handler),
    )

    assert client.provision_run_instruments("run-1", command) == receipt
    assert [request.url.path for request in requests] == [
        "/api/v1/runs/run-1/instruments/provision",
        "/api/v1/runs/run-1/instruments/provision",
    ]
    assert [
        RunInstrumentProvisionCommand.model_validate_json(request.content)
        for request in requests
    ] == [command, command]


def test_invoke_externalizes_inline_payload_before_command_post() -> None:
    requests: list[httpx2.Request] = []
    content = b"opaque-program"
    payload = command_payload_from_bytes(
        id="program-1",
        schema_id="pulse_program",
        codec_id="tests.raw",
        codec_version=1,
        media_type="application/octet-stream",
        content=content,
    )
    command = InvokeCommand(
        command_id="invoke-payload-1",
        instrument_id="source-0",
        resource_id="source-0",
        interface_id="test.play_program/v1",
        operation_id="play",
        arguments=[
            InstrumentOperationArgument(
                id="program",
                value=StateValue(PayloadRef(payload_id=payload.id)),
            )
        ],
        payloads={payload.id: payload},
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.method == "PUT":
            return _model(
                PayloadObjectReceipt(
                    ref=payload.content_hash,
                    content_hash=payload.content_hash,
                    size_bytes=len(content),
                ),
                status_code=201,
            )
        return _model(InvokeReceipt(status="invoked"))

    client = DaemonClient(
        "http://daemon.local/",
        transport=httpx2.MockTransport(handler),
    )

    assert (
        client.invoke_instrument("session-1", "source-0", command).status == "invoked"
    )
    assert [request.method for request in requests] == ["PUT", "POST"]
    assert requests[0].url.path == (
        "/api/v1/instrument-sessions/session-1/payload-objects/"
        f"{payload.content_hash.removeprefix('sha256:')}"
    )
    assert requests[0].content == content
    assert requests[1].url.path.endswith("/instruments/source-0/invoke")
    posted = InvokeCommand.model_validate_json(requests[1].content)
    posted_payload = posted.payloads[payload.id]
    assert isinstance(payload.body, InlinePayloadBody)
    assert isinstance(posted_payload.body, BlobPayloadBody)
    assert posted_payload.body.ref == payload.content_hash


def test_payload_object_put_retries_once_after_transport_failure() -> None:
    requests: list[httpx2.Request] = []
    content = b"retry-payload"
    payload = command_payload_from_bytes(
        id="retry-program",
        schema_id="pulse_program",
        codec_id="tests.raw",
        codec_version=1,
        media_type="application/octet-stream",
        content=content,
    )
    command = InvokeCommand(
        command_id="retry-invoke",
        instrument_id="source-0",
        resource_id="source-0",
        interface_id="test.play_program/v1",
        operation_id="play",
        arguments=[
            InstrumentOperationArgument(
                id="program",
                value=StateValue(PayloadRef(payload_id=payload.id)),
            )
        ],
        payloads={payload.id: payload},
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if len(requests) == 1:
            raise httpx2.ReadError("response was lost", request=request)
        if request.method == "PUT":
            return _model(
                PayloadObjectReceipt(
                    ref=payload.content_hash,
                    content_hash=payload.content_hash,
                    size_bytes=len(content),
                ),
                status_code=201,
            )
        return _model(InvokeReceipt(status="invoked"))

    client = DaemonClient(
        "http://daemon.local/",
        transport=httpx2.MockTransport(handler),
    )

    assert (
        client.invoke_instrument("session-1", "source-0", command).status == "invoked"
    )
    assert [request.method for request in requests] == ["PUT", "PUT", "POST"]
    assert requests[0].url == requests[1].url
    assert requests[0].content == requests[1].content == content


def test_not_found_and_conflict_are_typed_and_other_http_errors_raise() -> None:
    client = _client([])

    with pytest.raises(DaemonNotFoundError) as missing:
        client.get_run("missing")
    with pytest.raises(DaemonConflictError) as conflict:
        client.submit_run(_submission("duplicate"))
    with pytest.raises(httpx2.HTTPStatusError):
        client.get_run("invalid")

    assert missing.value.detail == "run was not found: missing"
    assert missing.value.response.status_code == 404
    assert conflict.value.detail == "submission already exists"
    assert conflict.value.response.status_code == 409


def _client(requests: list[httpx2.Request]) -> DaemonClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return _client_response(request)

    return DaemonClient(
        "http://daemon.local/",
        transport=httpx2.MockTransport(handler),
    )


def _client_response(request: httpx2.Request) -> httpx2.Response:
    path = request.url.path
    if path == "/api/v1/runs" and request.method == "GET":
        return _model(
            RunSummaryPage(
                items=(
                    RunSummary(
                        control=_control_run(),
                        manifest=_accepted_manifest(),
                    ),
                )
            )
        )
    if path == "/api/v1/runs/missing":
        return _json({"detail": "run was not found: missing"}, status_code=404)
    if path == "/api/v1/runs/invalid":
        return _json({"detail": "invalid request"}, status_code=422)
    if path == "/api/v1/runs" and request.method == "POST":
        if b'"submission_id":"duplicate"' in request.content:
            return _json(
                {"detail": "submission already exists"},
                status_code=409,
            )
        submission = RunSubmission.model_validate_json(request.content)
        return _model(_admission(submission.submission_id), status_code=201)
    raise AssertionError(f"unexpected request: {request.method} {path}")


def _model(model: BaseModel, *, status_code: int = 200) -> httpx2.Response:
    return _json(model.model_dump(mode="json"), status_code=status_code)


def _json(content: object, *, status_code: int = 200) -> httpx2.Response:
    return httpx2.Response(status_code, json=content)


def _control_run() -> ControlRun:
    return ControlRun(
        sequence=1,
        admission=RunAdmissionRecord(
            submission_id="submission-1",
            submission_content_hash="1" * 64,
            run_id="run-1",
            plan=RunPlanSummary(
                experiment_id="scratch",
                experiment_kind="scratch",
                point_count=1,
            ),
            admitted_at=_NOW,
        ),
        state="queued",
        updated_at=_NOW,
    )


def _admission(submission_id: str) -> RunAdmission:
    return RunAdmission(
        submission_id=submission_id,
        manifest=_accepted_manifest(),
    )


def _submission(submission_id: str = "submission-1") -> RunSubmission:
    return RunSubmission(
        submission_id=submission_id,
        config=load_config(),
        request=_REQUEST,
        plan=RunPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=1,
        ),
    )


def _lease() -> ExecutorLease:
    return ExecutorLease(
        lease_id="lease-1",
        run_id="run-1",
        executor_id="notebook-1",
        issued_at=_NOW,
        expires_at=_NOW + timedelta(seconds=30),
        heartbeat_interval_seconds=10,
    )


def _accepted_manifest() -> RunManifest:
    return RunManifest(
        run_id="run-1",
        created_at=_NOW,
        config_content_hash=_HASH,
    )

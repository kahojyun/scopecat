"""FastAPI boundary for a daemon application service."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path, PurePosixPath
from typing import Annotated, cast, override

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi import Path as ApiPath
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from scopecat.control.models import (
    ControlRunState,
    EventPage,
)
from scopecat.daemon.views import (
    ActiveConfigView,
    ConfigActivationHistoryView,
    ConfigDraftPreview,
    ConfigEntryView,
    ConfigRegistryView,
    DaemonHealth,
    InstrumentListView,
    InstrumentView,
    MeasurementPage,
    ParameterProposalListView,
    RunAnalysisListView,
    RunAnalysisView,
    RunArtifactBytesView,
    RunConfigView,
    RunDetail,
    RunRequestView,
    RunSummaryPage,
)
from scopecat.daemon.wire import (
    AnalysisSaveCommand,
    AnalysisSaveReceipt,
    AttentionResolutionReceipt,
    ConfigActivationReceipt,
    ConfigDraftCommand,
    ConfigEntryActivationCommand,
    ConfigPublishCommand,
    ConfigPublishReceipt,
    ConfigUndoCommand,
    ExecutionTransitionAppend,
    ExecutorHeartbeat,
    ExecutorLease,
    ExecutorStartRequest,
    InstrumentSessionEndReceipt,
    InstrumentSessionOpenCommand,
    InstrumentSessionOpenReceipt,
    MeasurementAppendCommand,
    MeasurementSealCommand,
    PayloadObjectReceipt,
    RunAdmission,
    RunAttachmentCommand,
    RunHardwareBatchCommand,
    RunHardwareFinishCommand,
    RunInstrumentProvisionCommand,
    RunInstrumentProvisionReceipt,
    RunSubmission,
    TerminalRunCommitCommand,
)
from scopecat.execution.ports.instruments import (
    RunHardwareBatchReceipt,
    RunHardwareFinalizationReceipt,
)
from scopecat.records.artifact import RunContentEntry
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.records.measurement_recording import MeasurementDatasetReceipt
from scopecat.records.run import RunManifest
from scopecat.runs.data import (
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunMeasurementDatasetResult,
    RunRecordJsonResult,
)
from scopecat.sdk.instruments.contracts import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    InstrumentStateCommand,
    InvokeCommand,
    InvokeReceipt,
)
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .application import DaemonApplication
from .errors import BackendConflict, BackendNotFound
from .payload_service import (
    CommandPayloadError,
    CommandPayloadStorageError,
    CommandPayloadTooLarge,
)

_API_PREFIX = "/api/v1"
_SSE_PAGE_SIZE = 100
_SSE_POLL_SECONDS = 0.5
DEFAULT_MAX_COMMAND_BODY_BYTES = 8 * 1024 * 1024


def create_app(  # noqa: C901 - route registration is intentionally centralized
    application: DaemonApplication,
    static_dir: str | Path | None = None,
    *,
    max_command_body_bytes: int = DEFAULT_MAX_COMMAND_BODY_BYTES,
) -> FastAPI:
    """Create transport routes around an already-composed daemon application."""

    app = FastAPI(title="Scopecat daemon", version="1")
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"],
    )
    app.add_middleware(
        _CommandBodyLimitMiddleware,
        max_body_bytes=max_command_body_bytes,
    )
    _install_error_mapping(app)

    @app.get(f"{_API_PREFIX}/health")
    def health() -> DaemonHealth:
        return application.health()

    @app.put(
        f"{_API_PREFIX}/instrument-sessions/{{session_id}}/"
        "payload-objects/{hexdigest}",
        status_code=201,
    )
    async def put_session_payload_object(
        session_id: str,
        hexdigest: Annotated[str, ApiPath(pattern=r"^[0-9a-f]{64}$")],
        request: Request,
    ) -> PayloadObjectReceipt:
        application.instruments.authorize_session_payload_upload(session_id)
        return await application.payloads.put_object_stream(
            request.stream(),
            expected_content_hash=f"sha256:{hexdigest}",
            declared_size_bytes=_request_content_length(request),
        )

    @app.put(
        f"{_API_PREFIX}/runs/{{run_id}}/payload-objects/{{hexdigest}}",
        status_code=201,
    )
    async def put_run_payload_object(
        run_id: str,
        hexdigest: Annotated[str, ApiPath(pattern=r"^[0-9a-f]{64}$")],
        request: Request,
        lease_id: Annotated[
            str,
            Header(alias="X-Scopecat-Lease-ID", min_length=1),
        ],
    ) -> PayloadObjectReceipt:
        application.instruments.authorize_run_payload_upload(run_id, lease_id)
        return await application.payloads.put_object_stream(
            request.stream(),
            expected_content_hash=f"sha256:{hexdigest}",
            declared_size_bytes=_request_content_length(request),
        )

    @app.get(f"{_API_PREFIX}/config-registry")
    def get_config_registry() -> ConfigRegistryView:
        return application.config.get_config_registry()

    @app.get(f"{_API_PREFIX}/config-registry/activations")
    def get_config_activation_history() -> ConfigActivationHistoryView:
        return application.config.get_config_activation_history()

    @app.get(f"{_API_PREFIX}/config-registry/active")
    def get_active_config() -> ActiveConfigView:
        return application.config.get_active_config()

    @app.get(f"{_API_PREFIX}/config-registry/entries/{{entry_id}}")
    def get_config_entry(entry_id: str) -> ConfigEntryView:
        return application.config.get_config_entry(entry_id)

    @app.post(f"{_API_PREFIX}/config-registry/default")
    def publish_config(command: ConfigPublishCommand) -> ConfigPublishReceipt:
        return application.config.publish_config(command)

    @app.post(f"{_API_PREFIX}/config-registry/drafts/preview")
    def preview_config_draft(
        command: ConfigDraftCommand,
    ) -> ConfigDraftPreview:
        return application.config.preview_config_draft(command)

    @app.post(f"{_API_PREFIX}/config-registry/active")
    def activate_config_entry(
        command: ConfigEntryActivationCommand,
    ) -> ConfigActivationReceipt:
        return application.config.activate_config_entry(command)

    @app.post(f"{_API_PREFIX}/config-registry/undo")
    def undo_config(
        command: ConfigUndoCommand,
    ) -> ConfigActivationReceipt:
        return application.config.undo_config(command)

    @app.get(f"{_API_PREFIX}/instruments")
    def list_instruments() -> InstrumentListView:
        return application.instruments.list_instruments()

    @app.get(f"{_API_PREFIX}/instruments/{{instrument_id}}")
    def get_instrument(instrument_id: str) -> InstrumentView:
        return application.instruments.get_instrument(instrument_id)

    @app.post(f"{_API_PREFIX}/instrument-sessions", status_code=201)
    def open_instrument_session(
        command: InstrumentSessionOpenCommand,
    ) -> InstrumentSessionOpenReceipt:
        return application.instruments.open_session(command)

    @app.get(
        f"{_API_PREFIX}/instrument-sessions/{{session_id}}/instruments/"
        "{instrument_id}/state"
    )
    def read_instrument_state(
        session_id: str,
        instrument_id: str,
    ) -> InstrumentStateSnapshot:
        return application.instruments.read_state(
            session_id,
            instrument_id,
        )

    @app.post(
        f"{_API_PREFIX}/instrument-sessions/{{session_id}}/instruments/"
        "{instrument_id}/state/apply"
    )
    def apply_instrument_state(
        session_id: str,
        instrument_id: str,
        command: InstrumentStateCommand,
    ) -> ApplyReceipt:
        return application.instruments.apply_state(
            session_id,
            instrument_id,
            command,
        )

    @app.post(
        f"{_API_PREFIX}/instrument-sessions/{{session_id}}/instruments/"
        "{instrument_id}/invoke"
    )
    def invoke_instrument(
        session_id: str,
        instrument_id: str,
        command: InvokeCommand,
    ) -> InvokeReceipt:
        return application.instruments.invoke(
            session_id,
            instrument_id,
            command,
        )

    @app.post(
        f"{_API_PREFIX}/instrument-sessions/{{session_id}}/instruments/"
        "{instrument_id}/collect"
    )
    def collect_instrument(
        session_id: str,
        instrument_id: str,
        command: CollectCommand,
    ) -> CollectReceipt:
        return application.instruments.collect(
            session_id,
            instrument_id,
            command,
        )

    @app.post(f"{_API_PREFIX}/instrument-sessions/{{session_id}}/close")
    def close_instrument_session(
        session_id: str,
    ) -> InstrumentSessionEndReceipt:
        return application.instruments.close_session(session_id)

    @app.post(f"{_API_PREFIX}/instrument-sessions/{{session_id}}/abort")
    def abort_instrument_session(
        session_id: str,
    ) -> InstrumentSessionEndReceipt:
        return application.instruments.abort_session(session_id)

    @app.post(f"{_API_PREFIX}/instrument-sessions/{{session_id}}/attention")
    def resolve_instrument_session_attention(
        session_id: str,
    ) -> InstrumentSessionEndReceipt:
        return application.instruments.resolve_attention(session_id)

    @app.get(f"{_API_PREFIX}/runs")
    def list_runs(
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        before: Annotated[int | None, Query(ge=1)] = None,
        state: ControlRunState | None = None,
    ) -> RunSummaryPage:
        return application.runs.list_runs(
            limit=limit,
            before=before,
            state=state,
        )

    @app.post(f"{_API_PREFIX}/runs", status_code=201)
    def submit_run(submission: RunSubmission) -> RunAdmission:
        return application.submit_run(submission)

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}")
    def get_run(run_id: str) -> RunDetail:
        return application.runs.get_run(run_id)

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/config")
    def get_run_config(run_id: str) -> RunConfigView:
        return application.runs.get_run_config(run_id)

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/request")
    def get_run_request(run_id: str) -> RunRequestView:
        return application.runs.get_run_request(run_id)

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/analyses")
    def list_run_analyses(run_id: str) -> RunAnalysisListView:
        return application.runs.list_run_analyses(run_id)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/analyses", status_code=201)
    def save_run_analysis(
        run_id: str,
        command: AnalysisSaveCommand,
    ) -> AnalysisSaveReceipt:
        return application.runs.save_run_analysis(run_id, command)

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/analyses/{{selector}}")
    def get_run_analysis(run_id: str, selector: str) -> RunAnalysisView:
        return application.runs.get_run_analysis(run_id, selector)

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/artifacts/{{selector}}/bytes")
    def get_run_artifact_bytes(
        run_id: str,
        selector: str,
        expected_kind: str | None = None,
    ) -> RunArtifactBytesView:
        return application.runs.get_run_artifact_bytes(
            run_id,
            selector,
            expected_kind=expected_kind,
        )

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/artifacts/{{selector}}/text")
    def get_run_artifact_text(
        run_id: str,
        selector: str,
        expected_kind: str | None = None,
    ) -> RunArtifactTextResult:
        return application.runs.get_run_artifact_text(
            run_id,
            selector,
            expected_kind=expected_kind,
        )

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/artifacts/{{selector}}/json")
    def get_run_artifact_json(
        run_id: str,
        selector: str,
        expected_kind: str | None = None,
    ) -> RunArtifactJsonResult:
        return application.runs.get_run_artifact_json(
            run_id,
            selector,
            expected_kind=expected_kind,
        )

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/records/{{selector}}/json")
    def get_run_record_json(
        run_id: str,
        selector: str,
        expected_kind: str | None = None,
    ) -> RunRecordJsonResult:
        return application.runs.get_run_record_json(
            run_id,
            selector,
            expected_kind=expected_kind,
        )

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/datasets/{{selector}}")
    def get_run_dataset_content(
        run_id: str,
        selector: str,
    ) -> RunMeasurementDatasetResult:
        return application.runs.get_run_dataset_content(run_id, selector)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/attachments", status_code=201)
    def attach_run_content(
        run_id: str,
        command: RunAttachmentCommand,
    ) -> RunContentEntry:
        return application.runs.attach_run_content(run_id, command)

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/parameter-proposals")
    def list_parameter_proposals(run_id: str) -> ParameterProposalListView:
        return application.runs.list_parameter_proposals(run_id)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/attention")
    def resolve_attention(
        run_id: str,
    ) -> AttentionResolutionReceipt:
        return application.resolve_attention(run_id)

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/measurements")
    def measurements(
        run_id: str,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> MeasurementPage:
        return application.runs.measurements(run_id, limit=limit, offset=offset)

    @app.get(f"{_API_PREFIX}/events")
    def list_events(
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        after: Annotated[int | None, Query(ge=0)] = None,
        run_id: str | None = None,
        latest: bool = False,
    ) -> EventPage:
        return application.runs.list_events(
            limit=limit,
            after=after,
            run_id=run_id,
            latest=latest,
        )

    @app.get(f"{_API_PREFIX}/events/stream")
    async def stream_events(
        request: Request,
        after: Annotated[int | None, Query(ge=0)] = None,
        last_event_id: Annotated[
            int | None,
            Header(alias="Last-Event-ID", ge=0),
        ] = None,
        run_id: str | None = None,
        follow: bool = True,
    ) -> StreamingResponse:
        cursor = last_event_id if last_event_id is not None else after
        events = _event_stream(
            application,
            request,
            after=cursor,
            run_id=run_id,
            follow=follow,
        )
        return StreamingResponse(
            events,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/executor/start")
    def start_executor(
        run_id: str,
        request: ExecutorStartRequest,
    ) -> ExecutorLease:
        return application.executor.start_executor(run_id, request)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/executor/heartbeat")
    def heartbeat_executor(
        run_id: str,
        heartbeat: ExecutorHeartbeat,
    ) -> ExecutorLease:
        return application.executor.heartbeat_executor(run_id, heartbeat)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/instruments/provision")
    def provision_run_instruments(
        run_id: str,
        command: RunInstrumentProvisionCommand,
    ) -> RunInstrumentProvisionReceipt:
        return application.instruments.provision_run(run_id, command)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/hardware/execute")
    def execute_run_hardware(
        run_id: str,
        command: RunHardwareBatchCommand,
    ) -> RunHardwareBatchReceipt:
        return application.instruments.execute_run_hardware(run_id, command)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/hardware/finish")
    def finish_run_hardware(
        run_id: str,
        command: RunHardwareFinishCommand,
    ) -> RunHardwareFinalizationReceipt:
        return application.instruments.finish_run_hardware(run_id, command)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/transitions")
    def append_transition(
        run_id: str,
        command: ExecutionTransitionAppend,
    ) -> ExecutionTransition:
        _require_run_id(run_id, command.transition.run_id)
        return application.executor.append_transition(run_id, command)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/measurements/append")
    def append_measurements(
        run_id: str,
        command: MeasurementAppendCommand,
    ) -> MeasurementDatasetReceipt:
        _require_run_id(run_id, command.append.run_id)
        return application.executor.append_measurements(run_id, command)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/measurements/seal")
    def seal_measurements(
        run_id: str,
        command: MeasurementSealCommand,
    ) -> MeasurementDatasetReceipt:
        _require_run_id(run_id, command.seal.run_id)
        return application.executor.seal_measurements(run_id, command)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/terminal")
    def commit_terminal(
        run_id: str,
        command: TerminalRunCommitCommand,
    ) -> RunManifest:
        _require_run_id(run_id, command.outcome.run_id)
        return application.executor.commit_terminal(run_id, command)

    if static_dir is not None:
        root = Path(static_dir)
        if not (root / "index.html").is_file():
            raise ValueError("static_dir must contain index.html")
        app.mount(
            "/",
            _SpaStaticFiles(directory=root, html=True),
            name="gui",
        )
    return app


def _install_error_mapping(app: FastAPI) -> None:
    @app.exception_handler(CommandPayloadTooLarge)
    async def payload_too_large(
        _request: Request,
        error: CommandPayloadTooLarge,
    ) -> JSONResponse:
        return JSONResponse(status_code=413, content={"detail": str(error)})

    @app.exception_handler(CommandPayloadStorageError)
    async def payload_storage_failure(
        _request: Request,
        error: CommandPayloadStorageError,
    ) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(error)})

    @app.exception_handler(CommandPayloadError)
    async def invalid_payload(
        _request: Request,
        error: CommandPayloadError,
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.exception_handler(BackendNotFound)
    async def not_found(
        _request: Request,
        error: BackendNotFound,
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(BackendConflict)
    async def conflict(
        _request: Request,
        error: BackendConflict,
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})


async def _event_stream(
    application: DaemonApplication,
    request: Request,
    *,
    after: int | None,
    run_id: str | None,
    follow: bool,
) -> AsyncIterator[str]:
    cursor = after
    while True:
        page = await run_in_threadpool(
            application.runs.list_events,
            limit=_SSE_PAGE_SIZE,
            after=cursor,
            run_id=run_id,
            latest=False,
        )
        for event in page.items:
            cursor = event.event_id
            yield _encode_sse(event.event_id, event.model_dump_json())
        if page.next_cursor is not None:
            cursor = page.next_cursor
            continue
        if not follow or await request.is_disconnected():
            return
        await asyncio.sleep(_SSE_POLL_SECONDS)


def _encode_sse(event_id: int, data: str) -> str:
    return f"id: {event_id}\nevent: project\ndata: {data}\n\n"


def _require_run_id(path_run_id: str, body_run_id: str) -> None:
    if path_run_id != body_run_id:
        raise HTTPException(
            status_code=422,
            detail="path run_id must match request body",
        )


class _CommandBodyTooLarge(Exception):
    """The JSON command body crossed the executable request boundary."""


class _CommandBodyLimitMiddleware:
    """Bound command JSON while leaving FastAPI request schemas intact."""

    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        if max_body_bytes < 1:
            raise ValueError("command body byte limit must be positive")
        self._app = app
        self._max_body_bytes = max_body_bytes

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if not _is_payload_command_request(scope):
            await self._app(scope, receive, send)
            return
        content_length = _content_length(scope)
        if content_length is not None and content_length > self._max_body_bytes:
            await self._reject(scope, receive, send)
            return
        size_bytes = 0

        async def bounded_receive() -> Message:
            nonlocal size_bytes
            message = await receive()
            if message["type"] == "http.request":
                body = cast("bytes", message.get("body", b""))
                size_bytes += len(body)
                if size_bytes > self._max_body_bytes:
                    raise _CommandBodyTooLarge
            return message

        try:
            await self._app(scope, bounded_receive, send)
        except _CommandBodyTooLarge:
            await self._reject(scope, receive, send)

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "detail": (
                    f"command request body exceeds {self._max_body_bytes} byte limit"
                )
            },
        )
        await response(scope, receive, send)


def _is_payload_command_request(scope: Scope) -> bool:
    method = cast("str | None", scope.get("method"))
    if scope["type"] != "http" or method != "POST":
        return False
    path = cast("str", scope.get("path", ""))
    return path.endswith(("/invoke", "/hardware/execute"))


def _content_length(scope: Scope) -> int | None:
    headers = cast("tuple[tuple[bytes, bytes], ...]", scope.get("headers", ()))
    for name, value in headers:
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


def _request_content_length(request: Request) -> int | None:
    return _content_length(request.scope)


class _SpaStaticFiles(StaticFiles):
    """Serve real files, then route extensionless GUI paths to the SPA."""

    @override
    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as error:
            if not _is_spa_path(path) or error.status_code != 404:
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404 and _is_spa_path(path):
            return await super().get_response("index.html", scope)
        return response


def _is_spa_path(path: str) -> bool:
    normalized = path.lstrip("/")
    return not normalized.startswith("api/") and not PurePosixPath(normalized).suffix

"""FastAPI boundary for a daemon application service."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path, PurePosixPath
from typing import Annotated, override

from fastapi import FastAPI, Header, HTTPException, Query, Request
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
    ConfigRevisionDefaultCommand,
    ConfigRevisionDefaultReceipt,
    ConfigRevisionRegistrationCommand,
    ConfigRevisionRegistrationReceipt,
    ConfigRollbackCommand,
    ExecutionTransitionAppend,
    ExecutorHeartbeat,
    ExecutorLease,
    ExecutorStartRequest,
    MeasurementAppendCommand,
    MeasurementSealCommand,
    ParameterProposalApprovalCommand,
    RunAdmission,
    RunAttachmentCommand,
    RunSubmission,
    TerminalRunCommitCommand,
)
from scopecat.records.artifact import RunContentEntry
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.measurement_recording import MeasurementDatasetReceipt
from scopecat.records.parameter_change import ParameterChangeApprovalRecord
from scopecat.records.run import RunManifest
from scopecat.runs.data import (
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunMeasurementDatasetResult,
    RunRecordJsonResult,
)
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import Scope

from .application import DaemonApplication
from .errors import BackendConflict, BackendNotFound

_API_PREFIX = "/api/v1"
_SSE_PAGE_SIZE = 100
_SSE_POLL_SECONDS = 0.5


def create_app(  # noqa: C901 - route registration is intentionally centralized
    application: DaemonApplication,
    static_dir: str | Path | None = None,
) -> FastAPI:
    """Create transport routes around an already-composed daemon application."""

    app = FastAPI(title="Scopecat daemon", version="1")
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"],
    )
    _install_error_mapping(app)

    @app.get(f"{_API_PREFIX}/health")
    def health() -> DaemonHealth:
        return application.health()

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

    @app.post(f"{_API_PREFIX}/config-registry/entries", status_code=201)
    def register_config_revision(
        command: ConfigRevisionRegistrationCommand,
    ) -> ConfigRevisionRegistrationReceipt:
        return application.config.register_config_revision(command)

    @app.post(f"{_API_PREFIX}/config-registry/default")
    def set_config_default(
        command: ConfigRevisionDefaultCommand,
    ) -> ConfigRevisionDefaultReceipt:
        return application.config.set_config_default(command)

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

    @app.post(f"{_API_PREFIX}/config-registry/rollback")
    def rollback_config(
        command: ConfigRollbackCommand,
    ) -> ConfigActivationReceipt:
        return application.config.rollback_config(command)

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

    @app.post(
        f"{_API_PREFIX}/runs/{{run_id}}/parameter-proposals/{{proposal_id}}/approval"
    )
    def approve_parameter_proposal(
        run_id: str,
        proposal_id: str,
        command: ParameterProposalApprovalCommand,
    ) -> ParameterChangeApprovalRecord:
        return application.runs.approve_parameter_proposal(
            run_id,
            proposal_id,
            command,
        )

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

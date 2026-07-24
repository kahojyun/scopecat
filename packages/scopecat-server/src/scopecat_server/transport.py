"""FastAPI boundary for a daemon application service."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path, PurePosixPath
from typing import Annotated, Protocol, override

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from scopecat.control.models import (
    ControlRunState,
    EventPage,
    RunPage,
)
from scopecat.daemon.views import (
    ActiveConfigView,
    ConfigEntryView,
    ConfigRegistryView,
    DaemonHealth,
    MeasurementPage,
    ParameterProposalListView,
    RunAnalysisListView,
    RunAnalysisView,
    RunArtifactBytesView,
    RunArtifactJsonView,
    RunArtifactTextView,
    RunConfigView,
    RunDatasetContentView,
    RunDetail,
    RunRecordJsonView,
    RunRequestView,
)
from scopecat.daemon.wire import (
    AnalysisSaveCommand,
    AnalysisSaveReceipt,
    AttentionResolutionCommand,
    AttentionResolutionReceipt,
    CandidateConfigActivationCommand,
    CandidateConfigActivationReceipt,
    CollectionCommitCommand,
    CollectionCommitReceipt,
    CollectionResolveCommand,
    CollectionResolveReceipt,
    ConfigActivationReceipt,
    ConfigEntryActivationCommand,
    ConfigImportReceipt,
    ConfigRollbackCommand,
    DirectConfigImportCommand,
    ExecutionRecoveryRequest,
    ExecutionRecoverySnapshot,
    ExecutionTransitionBatch,
    ExecutionTransitionBatchReceipt,
    ExecutorHeartbeat,
    ExecutorLease,
    ExecutorStartRequest,
    ExperimentCatalog,
    MeasurementAppendCommand,
    MeasurementAppendReceipt,
    MeasurementSealCommand,
    MeasurementSealReceipt,
    ParameterProposalReviewCommand,
    ParameterProposalReviewReceipt,
    PayloadCommitCommand,
    PayloadCommitReceipt,
    RunAdmission,
    RunAttachmentCommand,
    RunAttachmentReceipt,
    RunSubmission,
    TerminalRunCommitCommand,
    TerminalRunCommitReceipt,
)
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import Scope

from .errors import BackendConflict, BackendNotFound

_API_PREFIX = "/api/v1"
_SSE_PAGE_SIZE = 100
_SSE_POLL_SECONDS = 0.5


class DaemonBackend(Protocol):
    """Application-service contract consumed by the HTTP transport."""

    def health(self) -> DaemonHealth: ...

    def catalog(self) -> ExperimentCatalog: ...

    def get_config_registry(self) -> ConfigRegistryView: ...

    def get_active_config(self) -> ActiveConfigView: ...

    def get_config_entry(self, entry_id: str) -> ConfigEntryView: ...

    def import_direct_config(
        self,
        command: DirectConfigImportCommand,
    ) -> ConfigImportReceipt: ...

    def activate_config_entry(
        self,
        command: ConfigEntryActivationCommand,
    ) -> ConfigActivationReceipt: ...

    def rollback_config(
        self,
        command: ConfigRollbackCommand,
    ) -> ConfigActivationReceipt: ...

    def list_runs(
        self,
        *,
        limit: int,
        after: int | None,
        state: ControlRunState | None,
        latest: bool,
    ) -> RunPage: ...

    def submit_run(self, submission: RunSubmission) -> RunAdmission: ...

    def get_run(self, run_id: str) -> RunDetail: ...

    def get_run_config(self, run_id: str) -> RunConfigView: ...

    def get_run_request(self, run_id: str) -> RunRequestView: ...

    def list_run_analyses(self, run_id: str) -> RunAnalysisListView: ...

    def get_run_analysis(self, run_id: str, selector: str) -> RunAnalysisView: ...

    def save_run_analysis(
        self,
        run_id: str,
        command: AnalysisSaveCommand,
    ) -> AnalysisSaveReceipt: ...

    def get_run_artifact_bytes(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactBytesView: ...

    def get_run_artifact_text(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactTextView: ...

    def get_run_artifact_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactJsonView: ...

    def get_run_record_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunRecordJsonView: ...

    def get_run_dataset_content(
        self,
        run_id: str,
        selector: str,
    ) -> RunDatasetContentView: ...

    def attach_run_content(
        self,
        run_id: str,
        command: RunAttachmentCommand,
    ) -> RunAttachmentReceipt: ...

    def list_parameter_proposals(
        self,
        run_id: str,
    ) -> ParameterProposalListView: ...

    def review_parameter_proposal(
        self,
        run_id: str,
        command: ParameterProposalReviewCommand,
    ) -> ParameterProposalReviewReceipt: ...

    def activate_candidate_config(
        self,
        command: CandidateConfigActivationCommand,
    ) -> CandidateConfigActivationReceipt: ...

    def resolve_attention(
        self,
        run_id: str,
        command: AttentionResolutionCommand,
    ) -> AttentionResolutionReceipt: ...

    def measurements(
        self,
        run_id: str,
        *,
        limit: int,
        offset: int,
    ) -> MeasurementPage: ...

    def list_events(
        self,
        *,
        limit: int,
        after: int | None,
        run_id: str | None,
        latest: bool,
    ) -> EventPage: ...

    def start_executor(
        self,
        run_id: str,
        request: ExecutorStartRequest,
    ) -> ExecutorLease: ...

    def heartbeat_executor(
        self,
        run_id: str,
        heartbeat: ExecutorHeartbeat,
    ) -> ExecutorLease: ...

    def append_transitions(
        self,
        run_id: str,
        batch: ExecutionTransitionBatch,
    ) -> ExecutionTransitionBatchReceipt: ...

    def recover_execution(
        self,
        run_id: str,
        request: ExecutionRecoveryRequest,
    ) -> ExecutionRecoverySnapshot: ...

    def append_measurements(
        self,
        run_id: str,
        command: MeasurementAppendCommand,
    ) -> MeasurementAppendReceipt: ...

    def seal_measurements(
        self,
        run_id: str,
        command: MeasurementSealCommand,
    ) -> MeasurementSealReceipt: ...

    def commit_collection(
        self,
        run_id: str,
        command: CollectionCommitCommand,
    ) -> CollectionCommitReceipt: ...

    def resolve_collection(
        self,
        run_id: str,
        command: CollectionResolveCommand,
    ) -> CollectionResolveReceipt: ...

    def commit_payload(
        self,
        run_id: str,
        command: PayloadCommitCommand,
    ) -> PayloadCommitReceipt: ...

    def commit_terminal(
        self,
        run_id: str,
        command: TerminalRunCommitCommand,
    ) -> TerminalRunCommitReceipt: ...


def create_app(  # noqa: C901 - route registration is intentionally centralized
    backend: DaemonBackend,
    static_dir: str | Path | None = None,
) -> FastAPI:
    """Create transport routes around an already-composed daemon backend."""

    app = FastAPI(title="Scopecat daemon", version="1")
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"],
    )
    _install_error_mapping(app)

    @app.get(f"{_API_PREFIX}/health")
    def health() -> DaemonHealth:
        return backend.health()

    @app.get(f"{_API_PREFIX}/catalog")
    def catalog() -> ExperimentCatalog:
        return backend.catalog()

    @app.get(f"{_API_PREFIX}/config-registry")
    def get_config_registry() -> ConfigRegistryView:
        return backend.get_config_registry()

    @app.get(f"{_API_PREFIX}/config-registry/active")
    def get_active_config() -> ActiveConfigView:
        return backend.get_active_config()

    @app.get(f"{_API_PREFIX}/config-registry/entries/{{entry_id}}")
    def get_config_entry(entry_id: str) -> ConfigEntryView:
        return backend.get_config_entry(entry_id)

    @app.post(f"{_API_PREFIX}/config-registry/entries", status_code=201)
    def import_direct_config(
        command: DirectConfigImportCommand,
    ) -> ConfigImportReceipt:
        return backend.import_direct_config(command)

    @app.post(f"{_API_PREFIX}/config-registry/active")
    def activate_config_entry(
        command: ConfigEntryActivationCommand,
    ) -> ConfigActivationReceipt:
        return backend.activate_config_entry(command)

    @app.post(f"{_API_PREFIX}/config-registry/rollback")
    def rollback_config(
        command: ConfigRollbackCommand,
    ) -> ConfigActivationReceipt:
        return backend.rollback_config(command)

    @app.post(f"{_API_PREFIX}/config-registry/candidates/activate")
    def activate_candidate_config(
        command: CandidateConfigActivationCommand,
    ) -> CandidateConfigActivationReceipt:
        return backend.activate_candidate_config(command)

    @app.get(f"{_API_PREFIX}/runs")
    def list_runs(
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        after: Annotated[int | None, Query(ge=0)] = None,
        state: ControlRunState | None = None,
        latest: bool = False,
    ) -> RunPage:
        return backend.list_runs(
            limit=limit,
            after=after,
            state=state,
            latest=latest,
        )

    @app.post(f"{_API_PREFIX}/runs", status_code=201)
    def submit_run(submission: RunSubmission) -> RunAdmission:
        return backend.submit_run(submission)

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}")
    def get_run(run_id: str) -> RunDetail:
        return backend.get_run(run_id)

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/config")
    def get_run_config(run_id: str) -> RunConfigView:
        return backend.get_run_config(run_id)

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/request")
    def get_run_request(run_id: str) -> RunRequestView:
        return backend.get_run_request(run_id)

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/analyses")
    def list_run_analyses(run_id: str) -> RunAnalysisListView:
        return backend.list_run_analyses(run_id)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/analyses", status_code=201)
    def save_run_analysis(
        run_id: str,
        command: AnalysisSaveCommand,
    ) -> AnalysisSaveReceipt:
        _require_run_id(run_id, command.run_id)
        return backend.save_run_analysis(run_id, command)

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/analyses/{{selector}}")
    def get_run_analysis(run_id: str, selector: str) -> RunAnalysisView:
        return backend.get_run_analysis(run_id, selector)

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/artifacts/{{selector}}/bytes")
    def get_run_artifact_bytes(
        run_id: str,
        selector: str,
        expected_kind: str | None = None,
    ) -> RunArtifactBytesView:
        return backend.get_run_artifact_bytes(
            run_id,
            selector,
            expected_kind=expected_kind,
        )

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/artifacts/{{selector}}/text")
    def get_run_artifact_text(
        run_id: str,
        selector: str,
        expected_kind: str | None = None,
    ) -> RunArtifactTextView:
        return backend.get_run_artifact_text(
            run_id,
            selector,
            expected_kind=expected_kind,
        )

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/artifacts/{{selector}}/json")
    def get_run_artifact_json(
        run_id: str,
        selector: str,
        expected_kind: str | None = None,
    ) -> RunArtifactJsonView:
        return backend.get_run_artifact_json(
            run_id,
            selector,
            expected_kind=expected_kind,
        )

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/records/{{selector}}/json")
    def get_run_record_json(
        run_id: str,
        selector: str,
        expected_kind: str | None = None,
    ) -> RunRecordJsonView:
        return backend.get_run_record_json(
            run_id,
            selector,
            expected_kind=expected_kind,
        )

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/datasets/{{selector}}")
    def get_run_dataset_content(
        run_id: str,
        selector: str,
    ) -> RunDatasetContentView:
        return backend.get_run_dataset_content(run_id, selector)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/attachments", status_code=201)
    def attach_run_content(
        run_id: str,
        command: RunAttachmentCommand,
    ) -> RunAttachmentReceipt:
        _require_run_id(run_id, command.run_id)
        return backend.attach_run_content(run_id, command)

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/parameter-proposals")
    def list_parameter_proposals(run_id: str) -> ParameterProposalListView:
        return backend.list_parameter_proposals(run_id)

    @app.post(
        f"{_API_PREFIX}/runs/{{run_id}}/parameter-proposals/{{proposal_id}}/review"
    )
    def review_parameter_proposal(
        run_id: str,
        proposal_id: str,
        command: ParameterProposalReviewCommand,
    ) -> ParameterProposalReviewReceipt:
        _require_run_id(run_id, command.run_id)
        if proposal_id != command.proposal_id:
            raise HTTPException(
                status_code=422,
                detail="path proposal_id must match request body",
            )
        return backend.review_parameter_proposal(run_id, command)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/attention")
    def resolve_attention(
        run_id: str,
        command: AttentionResolutionCommand,
    ) -> AttentionResolutionReceipt:
        _require_run_id(run_id, command.run_id)
        return backend.resolve_attention(run_id, command)

    @app.get(f"{_API_PREFIX}/runs/{{run_id}}/measurements")
    def measurements(
        run_id: str,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> MeasurementPage:
        return backend.measurements(run_id, limit=limit, offset=offset)

    @app.get(f"{_API_PREFIX}/events")
    def list_events(
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        after: Annotated[int | None, Query(ge=0)] = None,
        run_id: str | None = None,
        latest: bool = False,
    ) -> EventPage:
        return backend.list_events(
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
            backend,
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
        _require_run_id(run_id, request.run_id)
        return backend.start_executor(run_id, request)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/executor/heartbeat")
    def heartbeat_executor(
        run_id: str,
        heartbeat: ExecutorHeartbeat,
    ) -> ExecutorLease:
        _require_run_id(run_id, heartbeat.run_id)
        return backend.heartbeat_executor(run_id, heartbeat)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/transitions")
    def append_transitions(
        run_id: str,
        batch: ExecutionTransitionBatch,
    ) -> ExecutionTransitionBatchReceipt:
        _require_run_id(run_id, batch.run_id)
        return backend.append_transitions(run_id, batch)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/execution/recovery")
    def recover_execution(
        run_id: str,
        request: ExecutionRecoveryRequest,
    ) -> ExecutionRecoverySnapshot:
        _require_run_id(run_id, request.run_id)
        return backend.recover_execution(run_id, request)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/measurements/append")
    def append_measurements(
        run_id: str,
        command: MeasurementAppendCommand,
    ) -> MeasurementAppendReceipt:
        _require_run_id(run_id, command.run_id)
        return backend.append_measurements(run_id, command)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/measurements/seal")
    def seal_measurements(
        run_id: str,
        command: MeasurementSealCommand,
    ) -> MeasurementSealReceipt:
        _require_run_id(run_id, command.run_id)
        return backend.seal_measurements(run_id, command)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/collections/commit")
    def commit_collection(
        run_id: str,
        command: CollectionCommitCommand,
    ) -> CollectionCommitReceipt:
        _require_run_id(run_id, command.run_id)
        return backend.commit_collection(run_id, command)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/collections/resolve")
    def resolve_collection(
        run_id: str,
        command: CollectionResolveCommand,
    ) -> CollectionResolveReceipt:
        _require_run_id(run_id, command.run_id)
        return backend.resolve_collection(run_id, command)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/payloads/commit")
    def commit_payload(
        run_id: str,
        command: PayloadCommitCommand,
    ) -> PayloadCommitReceipt:
        _require_run_id(run_id, command.run_id)
        return backend.commit_payload(run_id, command)

    @app.post(f"{_API_PREFIX}/runs/{{run_id}}/terminal")
    def commit_terminal(
        run_id: str,
        command: TerminalRunCommitCommand,
    ) -> TerminalRunCommitReceipt:
        _require_run_id(run_id, command.run_id)
        return backend.commit_terminal(run_id, command)

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
    backend: DaemonBackend,
    request: Request,
    *,
    after: int | None,
    run_id: str | None,
    follow: bool,
) -> AsyncIterator[str]:
    cursor = after
    while True:
        page = await run_in_threadpool(
            backend.list_events,
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

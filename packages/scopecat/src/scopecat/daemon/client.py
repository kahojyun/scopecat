"""Synchronous transport client for one project daemon."""

from __future__ import annotations

from types import TracebackType
from typing import Self
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

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
    AttentionResolutionAction,
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
    DelegatedRunSubmission,
    DirectConfigImportCommand,
    ExecutionRecoveryRequest,
    ExecutionRecoverySnapshot,
    ExecutionTransitionBatch,
    ExecutionTransitionBatchReceipt,
    ExecutorHeartbeat,
    ExecutorLease,
    ExecutorStartRequest,
    ExperimentCatalog,
    ManagedRunSubmission,
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
    TerminalRunCommitCommand,
    TerminalRunCommitReceipt,
)

_API_PREFIX = "/api/v1"


class DaemonClientError(RuntimeError):
    """Base class for errors translated from daemon responses."""

    def __init__(self, detail: str, *, response: httpx.Response) -> None:
        super().__init__(detail)
        self.detail = detail
        self.response = response


class DaemonNotFoundError(DaemonClientError):
    """The requested daemon object does not exist."""


class DaemonConflictError(DaemonClientError):
    """The command conflicts with current durable daemon state."""


class DaemonClient:
    """Thin synchronous wrapper around the versioned daemon HTTP API."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float | httpx.Timeout | None = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def health(self) -> DaemonHealth:
        return self._get_model(f"{_API_PREFIX}/health", DaemonHealth)

    def catalog(self) -> ExperimentCatalog:
        return self._get_model(f"{_API_PREFIX}/catalog", ExperimentCatalog)

    def config_registry(self) -> ConfigRegistryView:
        return self._get_model(
            f"{_API_PREFIX}/config-registry",
            ConfigRegistryView,
        )

    def active_config(self) -> ActiveConfigView:
        return self._get_model(
            f"{_API_PREFIX}/config-registry/active",
            ActiveConfigView,
        )

    def config_entry(self, entry_id: str) -> ConfigEntryView:
        return self._get_model(
            f"{_API_PREFIX}/config-registry/entries/{quote(entry_id, safe='')}",
            ConfigEntryView,
        )

    def import_direct_config(
        self,
        command: DirectConfigImportCommand,
    ) -> ConfigImportReceipt:
        return self._post_model(
            f"{_API_PREFIX}/config-registry/entries",
            command,
            ConfigImportReceipt,
        )

    def activate_config_entry(
        self,
        command: ConfigEntryActivationCommand,
    ) -> ConfigActivationReceipt:
        return self._post_model(
            f"{_API_PREFIX}/config-registry/active",
            command,
            ConfigActivationReceipt,
        )

    def rollback_config(
        self,
        command: ConfigRollbackCommand,
    ) -> ConfigActivationReceipt:
        return self._post_model(
            f"{_API_PREFIX}/config-registry/rollback",
            command,
            ConfigActivationReceipt,
        )

    def activate_candidate_config(
        self,
        command: CandidateConfigActivationCommand,
    ) -> CandidateConfigActivationReceipt:
        return self._post_model(
            f"{_API_PREFIX}/config-registry/candidates/activate",
            command,
            CandidateConfigActivationReceipt,
        )

    def list_runs(
        self,
        *,
        limit: int = 50,
        after: int | None = None,
        state: ControlRunState | None = None,
        latest: bool = False,
    ) -> RunPage:
        params: dict[str, str | int] = {"limit": limit}
        if after is not None:
            params["after"] = after
        if state is not None:
            params["state"] = state
        if latest:
            params["latest"] = "true"
        return self._get_model(f"{_API_PREFIX}/runs", RunPage, params=params)

    def get_run(self, run_id: str) -> RunDetail:
        return self._get_model(f"{_API_PREFIX}/runs/{run_id}", RunDetail)

    def run_config(self, run_id: str) -> RunConfigView:
        return self._get_model(
            f"{_API_PREFIX}/runs/{quote(run_id, safe='')}/config",
            RunConfigView,
        )

    def run_request(self, run_id: str) -> RunRequestView:
        return self._get_model(
            f"{_API_PREFIX}/runs/{quote(run_id, safe='')}/request",
            RunRequestView,
        )

    def analyses(self, run_id: str) -> RunAnalysisListView:
        return self._get_model(
            f"{_API_PREFIX}/runs/{quote(run_id, safe='')}/analyses",
            RunAnalysisListView,
        )

    def analysis(self, run_id: str, selector: str) -> RunAnalysisView:
        selected_run = quote(run_id, safe="")
        selected_analysis = quote(selector, safe="")
        return self._get_model(
            f"{_API_PREFIX}/runs/{selected_run}/analyses/{selected_analysis}",
            RunAnalysisView,
        )

    def save_analysis(self, command: AnalysisSaveCommand) -> AnalysisSaveReceipt:
        return self._post_model(
            f"{_API_PREFIX}/runs/{quote(command.run_id, safe='')}/analyses",
            command,
            AnalysisSaveReceipt,
        )

    def artifact_bytes(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactBytesView:
        return self._artifact_content(
            run_id,
            selector,
            representation="bytes",
            expected_kind=expected_kind,
            model=RunArtifactBytesView,
        )

    def artifact_text(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactTextView:
        return self._artifact_content(
            run_id,
            selector,
            representation="text",
            expected_kind=expected_kind,
            model=RunArtifactTextView,
        )

    def artifact_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactJsonView:
        return self._artifact_content(
            run_id,
            selector,
            representation="json",
            expected_kind=expected_kind,
            model=RunArtifactJsonView,
        )

    def _artifact_content[ArtifactViewT: BaseModel](
        self,
        run_id: str,
        selector: str,
        *,
        representation: str,
        expected_kind: str | None,
        model: type[ArtifactViewT],
    ) -> ArtifactViewT:
        selected_run = quote(run_id, safe="")
        selected_artifact = quote(selector, safe="")
        params: dict[str, str | int] | None = (
            None if expected_kind is None else {"expected_kind": expected_kind}
        )
        return self._get_model(
            (
                f"{_API_PREFIX}/runs/{selected_run}/artifacts/"
                f"{selected_artifact}/{representation}"
            ),
            model,
            params=params,
        )

    def record_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunRecordJsonView:
        selected_run = quote(run_id, safe="")
        selected_record = quote(selector, safe="")
        params: dict[str, str | int] | None = (
            None if expected_kind is None else {"expected_kind": expected_kind}
        )
        return self._get_model(
            f"{_API_PREFIX}/runs/{selected_run}/records/{selected_record}/json",
            RunRecordJsonView,
            params=params,
        )

    def dataset_content(
        self,
        run_id: str,
        selector: str,
    ) -> RunDatasetContentView:
        selected_run = quote(run_id, safe="")
        selected_dataset = quote(selector, safe="")
        return self._get_model(
            f"{_API_PREFIX}/runs/{selected_run}/datasets/{selected_dataset}",
            RunDatasetContentView,
        )

    def attach(self, command: RunAttachmentCommand) -> RunAttachmentReceipt:
        return self._post_model(
            f"{_API_PREFIX}/runs/{quote(command.run_id, safe='')}/attachments",
            command,
            RunAttachmentReceipt,
        )

    def parameter_proposals(self, run_id: str) -> ParameterProposalListView:
        return self._get_model(
            f"{_API_PREFIX}/runs/{quote(run_id, safe='')}/parameter-proposals",
            ParameterProposalListView,
        )

    def review_parameter_proposal(
        self,
        command: ParameterProposalReviewCommand,
    ) -> ParameterProposalReviewReceipt:
        run_id = quote(command.run_id, safe="")
        proposal_id = quote(command.proposal_id, safe="")
        return self._post_model(
            f"{_API_PREFIX}/runs/{run_id}/parameter-proposals/{proposal_id}/review",
            command,
            ParameterProposalReviewReceipt,
        )

    def resolve_attention(
        self,
        run_id: str,
        action: AttentionResolutionAction,
    ) -> AttentionResolutionReceipt:
        return self._post_model(
            f"{_API_PREFIX}/runs/{run_id}/attention",
            AttentionResolutionCommand(run_id=run_id, action=action),
            AttentionResolutionReceipt,
        )

    def measurements(
        self,
        run_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> MeasurementPage:
        return self._get_model(
            f"{_API_PREFIX}/runs/{run_id}/measurements",
            MeasurementPage,
            params={"limit": limit, "offset": offset},
        )

    def replay_events(
        self,
        *,
        limit: int = 100,
        after: int | None = None,
        run_id: str | None = None,
        latest: bool = False,
    ) -> EventPage:
        params: dict[str, str | int] = {"limit": limit}
        if after is not None:
            params["after"] = after
        if run_id is not None:
            params["run_id"] = run_id
        if latest:
            params["latest"] = "true"
        return self._get_model(f"{_API_PREFIX}/events", EventPage, params=params)

    def submit_managed(self, submission: ManagedRunSubmission) -> RunAdmission:
        return self._post_model(
            f"{_API_PREFIX}/runs",
            submission,
            RunAdmission,
        )

    def submit_delegated(self, submission: DelegatedRunSubmission) -> RunAdmission:
        return self._post_model(
            f"{_API_PREFIX}/runs",
            submission,
            RunAdmission,
        )

    def start_executor(
        self,
        request: ExecutorStartRequest,
    ) -> ExecutorLease:
        return self._post_model(
            f"{_API_PREFIX}/runs/{request.run_id}/executor/start",
            request,
            ExecutorLease,
        )

    def heartbeat_executor(
        self,
        run_id: str,
        heartbeat: ExecutorHeartbeat,
    ) -> ExecutorLease:
        return self._post_model(
            f"{_API_PREFIX}/runs/{run_id}/executor/heartbeat",
            heartbeat,
            ExecutorLease,
        )

    def append_transitions(
        self,
        batch: ExecutionTransitionBatch,
    ) -> ExecutionTransitionBatchReceipt:
        return self._post_model(
            f"{_API_PREFIX}/runs/{batch.run_id}/transitions",
            batch,
            ExecutionTransitionBatchReceipt,
        )

    def recover_execution(
        self,
        request: ExecutionRecoveryRequest,
    ) -> ExecutionRecoverySnapshot:
        return self._post_model(
            f"{_API_PREFIX}/runs/{request.run_id}/execution/recovery",
            request,
            ExecutionRecoverySnapshot,
        )

    def append_measurements(
        self,
        command: MeasurementAppendCommand,
    ) -> MeasurementAppendReceipt:
        return self._post_model(
            f"{_API_PREFIX}/runs/{command.run_id}/measurements/append",
            command,
            MeasurementAppendReceipt,
        )

    def seal_measurements(
        self,
        command: MeasurementSealCommand,
    ) -> MeasurementSealReceipt:
        return self._post_model(
            f"{_API_PREFIX}/runs/{command.run_id}/measurements/seal",
            command,
            MeasurementSealReceipt,
        )

    def commit_collection(
        self,
        command: CollectionCommitCommand,
    ) -> CollectionCommitReceipt:
        return self._post_model(
            f"{_API_PREFIX}/runs/{command.run_id}/collections/commit",
            command,
            CollectionCommitReceipt,
        )

    def resolve_collection(
        self,
        command: CollectionResolveCommand,
    ) -> CollectionResolveReceipt:
        return self._post_model(
            f"{_API_PREFIX}/runs/{command.run_id}/collections/resolve",
            command,
            CollectionResolveReceipt,
        )

    def commit_payload(
        self,
        command: PayloadCommitCommand,
    ) -> PayloadCommitReceipt:
        return self._post_model(
            f"{_API_PREFIX}/runs/{command.run_id}/payloads/commit",
            command,
            PayloadCommitReceipt,
        )

    def commit_terminal(
        self,
        command: TerminalRunCommitCommand,
    ) -> TerminalRunCommitReceipt:
        return self._post_model(
            f"{_API_PREFIX}/runs/{command.run_id}/terminal",
            command,
            TerminalRunCommitReceipt,
        )

    def _get_model[ModelT: BaseModel](
        self,
        path: str,
        model: type[ModelT],
        *,
        params: dict[str, str | int] | None = None,
    ) -> ModelT:
        response = self._request("GET", path, params=params)
        return model.model_validate_json(response.content)

    def _post_model[ModelT: BaseModel](
        self,
        path: str,
        body: BaseModel,
        model: type[ModelT],
    ) -> ModelT:
        response = self._request(
            "POST",
            path,
            json=body.model_dump(mode="json"),
        )
        return model.model_validate_json(response.content)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        json: object | None = None,
    ) -> httpx.Response:
        response = self._http.request(method, path, params=params, json=json)
        if response.status_code == 404:
            raise DaemonNotFoundError(_error_detail(response), response=response)
        if response.status_code == 409:
            raise DaemonConflictError(_error_detail(response), response=response)
        response.raise_for_status()
        return response


class _ErrorResponse(BaseModel):
    detail: str


def _error_detail(response: httpx.Response) -> str:
    try:
        return _ErrorResponse.model_validate_json(response.content).detail
    except ValidationError:
        return response.text or response.reason_phrase


__all__ = [
    "DaemonClient",
    "DaemonClientError",
    "DaemonConflictError",
    "DaemonHealth",
    "DaemonNotFoundError",
]

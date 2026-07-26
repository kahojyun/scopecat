"""Synchronous transport client for one project daemon."""

from __future__ import annotations

from types import TracebackType
from typing import Self
from urllib.parse import quote

import httpx2
from pydantic import BaseModel, ValidationError

from scopecat.config.registry.records import ConfigRegistryEntry
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
    CandidateConfigActivationCommand,
    CandidateConfigActivationReceipt,
    ConfigActivationReceipt,
    ConfigDefaultReceipt,
    ConfigDraftCommand,
    ConfigDraftDefaultCommand,
    ConfigDraftDefaultReceipt,
    ConfigDraftRegistrationCommand,
    ConfigDraftRegistrationReceipt,
    ConfigEntryActivationCommand,
    ConfigRollbackCommand,
    DirectConfigDefaultCommand,
    DirectConfigImportCommand,
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

_API_PREFIX = "/api/v1"


class DaemonClientError(RuntimeError):
    """Base class for errors translated from daemon responses."""

    def __init__(self, detail: str, *, response: httpx2.Response) -> None:
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
        timeout: float | httpx2.Timeout | None = 10.0,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._http = httpx2.Client(
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

    def config_registry(self) -> ConfigRegistryView:
        return self._get_model(
            f"{_API_PREFIX}/config-registry",
            ConfigRegistryView,
        )

    def config_activation_history(self) -> ConfigActivationHistoryView:
        return self._get_model(
            f"{_API_PREFIX}/config-registry/activations",
            ConfigActivationHistoryView,
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
    ) -> ConfigRegistryEntry:
        return self._post_model(
            f"{_API_PREFIX}/config-registry/entries",
            command,
            ConfigRegistryEntry,
        )

    def set_direct_config_default(
        self,
        command: DirectConfigDefaultCommand,
    ) -> ConfigDefaultReceipt:
        return self._post_model(
            f"{_API_PREFIX}/config-registry/default",
            command,
            ConfigDefaultReceipt,
        )

    def preview_config_draft(
        self,
        command: ConfigDraftCommand,
    ) -> ConfigDraftPreview:
        return self._post_model(
            f"{_API_PREFIX}/config-registry/drafts/preview",
            command,
            ConfigDraftPreview,
        )

    def register_config_draft(
        self,
        command: ConfigDraftRegistrationCommand,
    ) -> ConfigDraftRegistrationReceipt:
        return self._post_model(
            f"{_API_PREFIX}/config-registry/drafts/register",
            command,
            ConfigDraftRegistrationReceipt,
        )

    def set_config_draft_default(
        self,
        command: ConfigDraftDefaultCommand,
    ) -> ConfigDraftDefaultReceipt:
        return self._post_model(
            f"{_API_PREFIX}/config-registry/drafts/set-default",
            command,
            ConfigDraftDefaultReceipt,
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
        before: int | None = None,
        state: ControlRunState | None = None,
        latest: bool = False,
    ) -> RunSummaryPage:
        params: dict[str, str | int] = {"limit": limit}
        if after is not None:
            params["after"] = after
        if before is not None:
            params["before"] = before
        if state is not None:
            params["state"] = state
        if latest:
            params["latest"] = "true"
        return self._get_model(f"{_API_PREFIX}/runs", RunSummaryPage, params=params)

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

    def save_analysis(
        self,
        run_id: str,
        command: AnalysisSaveCommand,
    ) -> AnalysisSaveReceipt:
        return self._post_model(
            f"{_API_PREFIX}/runs/{quote(run_id, safe='')}/analyses",
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
    ) -> RunArtifactTextResult:
        return self._artifact_content(
            run_id,
            selector,
            representation="text",
            expected_kind=expected_kind,
            model=RunArtifactTextResult,
        )

    def artifact_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactJsonResult:
        return self._artifact_content(
            run_id,
            selector,
            representation="json",
            expected_kind=expected_kind,
            model=RunArtifactJsonResult,
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
    ) -> RunRecordJsonResult:
        selected_run = quote(run_id, safe="")
        selected_record = quote(selector, safe="")
        params: dict[str, str | int] | None = (
            None if expected_kind is None else {"expected_kind": expected_kind}
        )
        return self._get_model(
            f"{_API_PREFIX}/runs/{selected_run}/records/{selected_record}/json",
            RunRecordJsonResult,
            params=params,
        )

    def dataset_content(
        self,
        run_id: str,
        selector: str,
    ) -> RunMeasurementDatasetResult:
        selected_run = quote(run_id, safe="")
        selected_dataset = quote(selector, safe="")
        return self._get_model(
            f"{_API_PREFIX}/runs/{selected_run}/datasets/{selected_dataset}",
            RunMeasurementDatasetResult,
        )

    def attach(
        self,
        run_id: str,
        command: RunAttachmentCommand,
    ) -> RunContentEntry:
        return self._post_model(
            f"{_API_PREFIX}/runs/{quote(run_id, safe='')}/attachments",
            command,
            RunContentEntry,
        )

    def parameter_proposals(self, run_id: str) -> ParameterProposalListView:
        return self._get_model(
            f"{_API_PREFIX}/runs/{quote(run_id, safe='')}/parameter-proposals",
            ParameterProposalListView,
        )

    def approve_parameter_proposal(
        self,
        run_id: str,
        proposal_id: str,
        command: ParameterProposalApprovalCommand,
    ) -> ParameterChangeApprovalRecord:
        selected_run = quote(run_id, safe="")
        selected_proposal = quote(proposal_id, safe="")
        return self._post_model(
            (
                f"{_API_PREFIX}/runs/{selected_run}/parameter-proposals/"
                f"{selected_proposal}/approval"
            ),
            command,
            ParameterChangeApprovalRecord,
        )

    def resolve_attention(
        self,
        run_id: str,
    ) -> AttentionResolutionReceipt:
        response = self._request(
            "POST",
            f"{_API_PREFIX}/runs/{run_id}/attention",
        )
        return AttentionResolutionReceipt.model_validate_json(response.content)

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

    def submit_run(self, submission: RunSubmission) -> RunAdmission:
        return self._post_model(
            f"{_API_PREFIX}/runs",
            submission,
            RunAdmission,
        )

    def start_executor(
        self,
        run_id: str,
        request: ExecutorStartRequest,
    ) -> ExecutorLease:
        lease = self._post_model(
            f"{_API_PREFIX}/runs/{run_id}/executor/start",
            request,
            ExecutorLease,
        )
        if lease.run_id != run_id:
            raise ValueError("executor lease does not match its request")
        return lease

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

    def append_transition(
        self,
        run_id: str,
        command: ExecutionTransitionAppend,
    ) -> ExecutionTransition:
        return self._post_model(
            f"{_API_PREFIX}/runs/{run_id}/transitions",
            command,
            ExecutionTransition,
        )

    def append_measurements(
        self,
        run_id: str,
        command: MeasurementAppendCommand,
    ) -> MeasurementDatasetReceipt:
        return self._post_model(
            f"{_API_PREFIX}/runs/{run_id}/measurements/append",
            command,
            MeasurementDatasetReceipt,
        )

    def seal_measurements(
        self,
        run_id: str,
        command: MeasurementSealCommand,
    ) -> MeasurementDatasetReceipt:
        return self._post_model(
            f"{_API_PREFIX}/runs/{run_id}/measurements/seal",
            command,
            MeasurementDatasetReceipt,
        )

    def commit_terminal(
        self,
        run_id: str,
        command: TerminalRunCommitCommand,
    ) -> RunManifest:
        return self._post_model(
            f"{_API_PREFIX}/runs/{run_id}/terminal",
            command,
            RunManifest,
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
    ) -> httpx2.Response:
        response = self._http.request(method, path, params=params, json=json)
        if response.status_code == 404:
            raise DaemonNotFoundError(_error_detail(response), response=response)
        if response.status_code == 409:
            raise DaemonConflictError(_error_detail(response), response=response)
        response.raise_for_status()
        return response


class _ErrorResponse(BaseModel):
    detail: str


def _error_detail(response: httpx2.Response) -> str:
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

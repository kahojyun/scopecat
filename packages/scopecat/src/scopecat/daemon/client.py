# pyright: reportUnknownMemberType=false, reportUnknownParameterType=false
# pyright: reportUnknownVariableType=false
"""Synchronous transport client for one project daemon."""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Self, cast
from urllib.parse import quote

import httpx2
import pyarrow as pa
from pydantic import BaseModel, ValidationError

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
    MeasurementArrowQuery,
    MeasurementTracePreview,
    MeasurementTracePreviewQuery,
    ParameterProposalListView,
    RunAnalysisListView,
    RunAnalysisView,
    RunArtifactBytesView,
    RunConfigView,
    RunDatasetBytesView,
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
    ExecutionTransitionClaim,
    ExecutorHeartbeat,
    ExecutorLease,
    ExecutorStartRequest,
    InstrumentConfiguredDefaultsApplyCommand,
    InstrumentConfiguredDefaultsApplyReceipt,
    InstrumentContractCatalogRequest,
    InstrumentDriverProbeCommand,
    InstrumentDriverProbeReceipt,
    InstrumentInventoryMigrationCommand,
    InstrumentInventoryMigrationReceipt,
    InstrumentSessionEndReceipt,
    InstrumentSessionLeaseReceipt,
    InstrumentSessionOpenCommand,
    InstrumentSessionOpenReceipt,
    MeasurementAppendCommand,
    MeasurementHeaderCommand,
    MeasurementSealCommand,
    PayloadObjectReceipt,
    RunAdmission,
    RunAttachmentCommand,
    RunCancellationReceipt,
    RunHardwareBatchCommand,
    RunHardwareFinishCommand,
    RunInstrumentProvisionCommand,
    RunInstrumentProvisionReceipt,
    RunSubmission,
    TerminalRunCommitCommand,
)
from scopecat.kernel.content_identity import sha256_content_hash
from scopecat.planning.catalog import InstrumentContractCatalog
from scopecat.records.artifact import (
    BlobPayloadBody,
    CommandPayload,
    InlinePayloadBody,
    RunContentEntry,
)
from scopecat.records.config import ConfigProfileSnapshot
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
from scopecat.sdk.instruments.catalog import DriverCatalog
from scopecat.sdk.instruments.commands import (
    ApplyReceipt,
    CollectReceipt,
    InstrumentStateCommand,
    InteractiveCollectIntent,
    InvokeCommand,
    InvokeReceipt,
)
from scopecat.sdk.instruments.execution import (
    RunHardwareBatchReceipt,
    RunHardwareFinalizationReceipt,
    RunHardwareInvoke,
)

_API_PREFIX = "/api/v1"
_NEXT_OFFSET_HEADER = "X-Scopecat-Next-Offset"
_SNAPSHOT_SIZE_HEADER = "X-Scopecat-Snapshot-Size"
# The daemon owns operation deadlines; a read timeout would make a completed
# hardware command ambiguous to its caller.
_DEFAULT_TIMEOUT = httpx2.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)


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


class DaemonUnavailableError(DaemonClientError):
    """The daemon temporarily cannot complete a retry-safe request."""


class DaemonClient:
    """Thin synchronous wrapper around the versioned daemon HTTP API."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float | httpx2.Timeout | None = _DEFAULT_TIMEOUT,
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

    def publish_config(
        self,
        command: ConfigPublishCommand,
    ) -> ConfigPublishReceipt:
        return self._post_model(
            f"{_API_PREFIX}/config-registry/default",
            command,
            ConfigPublishReceipt,
        )

    def migrate_instrument_inventory(
        self,
        command: InstrumentInventoryMigrationCommand,
    ) -> InstrumentInventoryMigrationReceipt:
        return self._post_model(
            f"{_API_PREFIX}/config-registry/instrument-inventory-migrations",
            command,
            InstrumentInventoryMigrationReceipt,
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

    def activate_config_entry(
        self,
        command: ConfigEntryActivationCommand,
    ) -> ConfigActivationReceipt:
        return self._post_model(
            f"{_API_PREFIX}/config-registry/active",
            command,
            ConfigActivationReceipt,
        )

    def undo_config(
        self,
        command: ConfigUndoCommand,
    ) -> ConfigActivationReceipt:
        return self._post_model(
            f"{_API_PREFIX}/config-registry/undo",
            command,
            ConfigActivationReceipt,
        )

    def list_instruments(self) -> InstrumentListView:
        return self._get_model(
            f"{_API_PREFIX}/instruments",
            InstrumentListView,
        )

    def driver_catalog(self) -> DriverCatalog:
        return self._get_model(
            f"{_API_PREFIX}/instrument-drivers",
            DriverCatalog,
        )

    def probe_driver(
        self,
        command: InstrumentDriverProbeCommand,
    ) -> InstrumentDriverProbeReceipt:
        return self._post_model(
            f"{_API_PREFIX}/instrument-drivers/probe",
            command,
            InstrumentDriverProbeReceipt,
        )

    def get_instrument(self, instrument_id: str) -> InstrumentView:
        return self._get_model(
            f"{_API_PREFIX}/instruments/{quote(instrument_id, safe='')}",
            InstrumentView,
        )

    def resolve_instrument_contracts(
        self,
        config: ConfigProfileSnapshot,
    ) -> InstrumentContractCatalog:
        return self._post_model(
            f"{_API_PREFIX}/instrument-contracts/resolve",
            InstrumentContractCatalogRequest(config=config),
            InstrumentContractCatalog,
        )

    def open_instrument_session(
        self,
        command: InstrumentSessionOpenCommand,
    ) -> InstrumentSessionOpenReceipt:
        return self._post_idempotent_model(
            f"{_API_PREFIX}/instrument-sessions",
            command,
            InstrumentSessionOpenReceipt,
        )

    def renew_instrument_session(
        self,
        session_id: str,
    ) -> InstrumentSessionLeaseReceipt:
        return self._post_empty_idempotent_model(
            (
                f"{_API_PREFIX}/instrument-sessions/"
                f"{quote(session_id, safe='')}/heartbeat"
            ),
            InstrumentSessionLeaseReceipt,
        )

    def read_instrument_state(
        self,
        session_id: str,
        instrument_id: str,
    ) -> InstrumentStateSnapshot:
        return self._get_model(
            self._instrument_session_path(
                session_id,
                instrument_id,
                "state",
            ),
            InstrumentStateSnapshot,
        )

    def apply_instrument_state(
        self,
        session_id: str,
        instrument_id: str,
        command: InstrumentStateCommand,
    ) -> ApplyReceipt:
        return self._post_idempotent_model(
            self._instrument_session_path(
                session_id,
                instrument_id,
                "state/apply",
            ),
            command,
            ApplyReceipt,
        )

    def apply_instrument_configured_defaults(
        self,
        session_id: str,
        instrument_id: str,
        command: InstrumentConfiguredDefaultsApplyCommand,
    ) -> InstrumentConfiguredDefaultsApplyReceipt:
        return self._post_idempotent_model(
            self._instrument_session_path(
                session_id,
                instrument_id,
                "configured-defaults/apply",
            ),
            command,
            InstrumentConfiguredDefaultsApplyReceipt,
        )

    def invoke_instrument(
        self,
        session_id: str,
        instrument_id: str,
        command: InvokeCommand,
    ) -> InvokeReceipt:
        command = self._externalize_invoke_command(session_id, command)
        return self._post_idempotent_model(
            self._instrument_session_path(
                session_id,
                instrument_id,
                "invoke",
            ),
            command,
            InvokeReceipt,
        )

    def collect_instrument(
        self,
        session_id: str,
        instrument_id: str,
        intent: InteractiveCollectIntent,
    ) -> CollectReceipt:
        return self._post_idempotent_model(
            self._instrument_session_path(
                session_id,
                instrument_id,
                "collect",
            ),
            intent,
            CollectReceipt,
        )

    def close_instrument_session(
        self,
        session_id: str,
    ) -> InstrumentSessionEndReceipt:
        return self._post_empty_idempotent_model(
            (f"{_API_PREFIX}/instrument-sessions/{quote(session_id, safe='')}/close"),
            InstrumentSessionEndReceipt,
        )

    def abort_instrument_session(
        self,
        session_id: str,
    ) -> InstrumentSessionEndReceipt:
        return self._post_empty_idempotent_model(
            (f"{_API_PREFIX}/instrument-sessions/{quote(session_id, safe='')}/abort"),
            InstrumentSessionEndReceipt,
        )

    def resolve_instrument_session_attention(
        self,
        session_id: str,
    ) -> InstrumentSessionEndReceipt:
        response = self._request(
            "POST",
            (
                f"{_API_PREFIX}/instrument-sessions/"
                f"{quote(session_id, safe='')}/attention"
            ),
        )
        return InstrumentSessionEndReceipt.model_validate_json(response.content)

    def list_runs(
        self,
        *,
        limit: int = 50,
        before: int | None = None,
        state: ControlRunState | None = None,
    ) -> RunSummaryPage:
        params: dict[str, str | int] = {"limit": limit}
        if before is not None:
            params["before"] = before
        if state is not None:
            params["state"] = state
        return self._get_model(f"{_API_PREFIX}/runs", RunSummaryPage, params=params)

    def get_run(self, run_id: str) -> RunDetail:
        return self._get_model(f"{_API_PREFIX}/runs/{run_id}", RunDetail)

    def cancel_run(self, run_id: str) -> RunCancellationReceipt:
        return self._post_empty_idempotent_model(
            f"{_API_PREFIX}/runs/{quote(run_id, safe='')}/cancel",
            RunCancellationReceipt,
        )

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

    def dataset_bytes(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunDatasetBytesView:
        selected_run = quote(run_id, safe="")
        selected_dataset = quote(selector, safe="")
        params: dict[str, str | int] | None = (
            None if expected_kind is None else {"expected_kind": expected_kind}
        )
        return self._get_model(
            f"{_API_PREFIX}/runs/{selected_run}/datasets/{selected_dataset}/bytes",
            RunDatasetBytesView,
            params=params,
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

    def resolve_attention(
        self,
        run_id: str,
    ) -> AttentionResolutionReceipt:
        response = self._request(
            "POST",
            f"{_API_PREFIX}/runs/{run_id}/attention",
        )
        return AttentionResolutionReceipt.model_validate_json(response.content)

    def measurement_arrow(
        self,
        run_id: str,
        query: MeasurementArrowQuery,
    ) -> tuple[pa.Table, int | None, int]:
        response = self._request(
            "POST",
            f"{_API_PREFIX}/runs/{quote(run_id, safe='')}/measurements/arrow",
            json=query.model_dump(mode="json"),
        )
        table = pa.ipc.open_stream(response.content).read_all()
        encoded_next_offset = cast(
            "str | None", response.headers.get(_NEXT_OFFSET_HEADER)
        )
        next_offset = None if encoded_next_offset is None else int(encoded_next_offset)
        encoded_snapshot_size = cast(
            "str | None", response.headers.get(_SNAPSHOT_SIZE_HEADER)
        )
        if encoded_snapshot_size is None:
            raise ValueError("measurement Arrow response has no snapshot size")
        return table, next_offset, int(encoded_snapshot_size)

    def measurement_trace_preview(
        self,
        run_id: str,
        query: MeasurementTracePreviewQuery,
    ) -> MeasurementTracePreview:
        return self._post_model(
            f"{_API_PREFIX}/runs/{quote(run_id, safe='')}/measurements/traces/query",
            query,
            MeasurementTracePreview,
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

    def provision_run_instruments(
        self,
        run_id: str,
        command: RunInstrumentProvisionCommand,
    ) -> RunInstrumentProvisionReceipt:
        return self._post_idempotent_model(
            f"{_API_PREFIX}/runs/{quote(run_id, safe='')}/instruments/provision",
            command,
            RunInstrumentProvisionReceipt,
        )

    def execute_run_hardware(
        self,
        run_id: str,
        command: RunHardwareBatchCommand,
    ) -> RunHardwareBatchReceipt:
        command = self._externalize_hardware_command(
            run_id,
            command.lease_id,
            command,
        )
        return self._post_idempotent_model(
            f"{_API_PREFIX}/runs/{quote(run_id, safe='')}/hardware/execute",
            command,
            RunHardwareBatchReceipt,
        )

    def finish_run_hardware(
        self,
        run_id: str,
        command: RunHardwareFinishCommand,
    ) -> RunHardwareFinalizationReceipt:
        return self._post_idempotent_model(
            f"{_API_PREFIX}/runs/{quote(run_id, safe='')}/hardware/finish",
            command,
            RunHardwareFinalizationReceipt,
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

    def claim_transition(
        self,
        run_id: str,
        command: ExecutionTransitionClaim,
    ) -> ExecutionTransition:
        return self._post_model(
            f"{_API_PREFIX}/runs/{run_id}/transitions/claim",
            command,
            ExecutionTransition,
        )

    def initialize_measurements(
        self,
        run_id: str,
        command: MeasurementHeaderCommand,
    ) -> MeasurementDatasetReceipt:
        return self._post_model(
            f"{_API_PREFIX}/runs/{run_id}/measurements/header",
            command,
            MeasurementDatasetReceipt,
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

    def _externalize_invoke_command(
        self,
        session_id: str,
        command: InvokeCommand,
    ) -> InvokeCommand:
        return command.model_copy(
            update={
                "payloads": self._externalize_payloads(
                    command.payloads,
                    upload_object=lambda content, content_hash: (
                        self._put_session_payload_object(
                            session_id,
                            content,
                            content_hash=content_hash,
                        )
                    ),
                )
            }
        )

    def _externalize_hardware_command(
        self,
        run_id: str,
        lease_id: str,
        command: RunHardwareBatchCommand,
    ) -> RunHardwareBatchCommand:
        uploaded: dict[str, PayloadObjectReceipt] = {}
        actions = tuple(
            action.model_copy(
                update={
                    "payloads": self._externalize_payloads(
                        action.payloads,
                        upload_object=lambda content, content_hash: (
                            self._put_run_payload_object(
                                run_id,
                                lease_id,
                                content,
                                content_hash=content_hash,
                            )
                        ),
                        uploaded=uploaded,
                    )
                }
            )
            if isinstance(action, RunHardwareInvoke)
            else action
            for action in command.batch.actions
        )
        return command.model_copy(
            update={"batch": command.batch.model_copy(update={"actions": actions})}
        )

    def _externalize_payloads(
        self,
        payloads: dict[str, CommandPayload],
        *,
        upload_object: Callable[[bytes, str], PayloadObjectReceipt],
        uploaded: dict[str, PayloadObjectReceipt] | None = None,
    ) -> dict[str, CommandPayload]:
        externalized: dict[str, CommandPayload] = {}
        uploaded_by_hash = uploaded if uploaded is not None else {}
        for payload_id, payload in payloads.items():
            if not isinstance(payload.body, InlinePayloadBody):
                externalized[payload_id] = payload
                continue
            receipt = uploaded_by_hash.get(payload.content_hash)
            if receipt is None:
                content = payload.inline_bytes()
                receipt = upload_object(content, payload.content_hash)
                uploaded_by_hash[payload.content_hash] = receipt
            externalized[payload_id] = payload.model_copy(
                update={"body": BlobPayloadBody(ref=receipt.ref)}
            )
        return externalized

    def _put_session_payload_object(
        self,
        session_id: str,
        content: bytes,
        *,
        content_hash: str,
    ) -> PayloadObjectReceipt:
        return self._put_payload_object(
            (
                f"{_API_PREFIX}/instrument-sessions/"
                f"{quote(session_id, safe='')}/payload-objects"
            ),
            content,
            content_hash=content_hash,
        )

    def _put_run_payload_object(
        self,
        run_id: str,
        lease_id: str,
        content: bytes,
        *,
        content_hash: str,
    ) -> PayloadObjectReceipt:
        return self._put_payload_object(
            f"{_API_PREFIX}/runs/{quote(run_id, safe='')}/payload-objects",
            content,
            content_hash=content_hash,
            headers={"X-Scopecat-Lease-ID": lease_id},
        )

    def _put_payload_object(
        self,
        scope_path: str,
        content: bytes,
        *,
        content_hash: str,
        headers: dict[str, str] | None = None,
    ) -> PayloadObjectReceipt:
        """Publish one immutable payload through an authorized scope."""

        actual_hash = sha256_content_hash(content)
        if content_hash != actual_hash:
            raise ValueError("payload content does not match content_hash")
        path = f"{scope_path}/{actual_hash.removeprefix('sha256:')}"
        response = self._put_payload_content(path, content, headers=headers)
        receipt = PayloadObjectReceipt.model_validate_json(response.content)
        if receipt.content_hash != content_hash or receipt.size_bytes != len(content):
            raise ValueError("daemon payload object receipt does not match upload")
        return receipt

    @staticmethod
    def _instrument_session_path(
        session_id: str,
        instrument_id: str,
        suffix: str,
    ) -> str:
        return (
            f"{_API_PREFIX}/instrument-sessions/{quote(session_id, safe='')}/"
            f"instruments/{quote(instrument_id, safe='')}/{suffix}"
        )

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

    def _post_idempotent_model[ModelT: BaseModel](
        self,
        path: str,
        body: BaseModel,
        model: type[ModelT],
    ) -> ModelT:
        """Retry one transport failure with the exact operation command."""

        try:
            return self._post_model(path, body, model)
        except httpx2.TransportError:
            return self._post_model(path, body, model)

    def _put_payload_content(
        self,
        path: str,
        content: bytes,
        *,
        headers: dict[str, str] | None = None,
    ) -> httpx2.Response:
        """Retry one transport failure against an immutable content PUT."""

        request_headers = {
            "Content-Type": "application/octet-stream",
            **(headers or {}),
        }
        try:
            return self._request(
                "PUT",
                path,
                content=content,
                headers=request_headers,
            )
        except httpx2.TransportError:
            return self._request(
                "PUT",
                path,
                content=content,
                headers=request_headers,
            )

    def _post_empty_idempotent_model[ModelT: BaseModel](
        self,
        path: str,
        model: type[ModelT],
    ) -> ModelT:
        """Retry one transport failure against an idempotent empty command."""

        try:
            response = self._request("POST", path)
        except httpx2.TransportError:
            response = self._request("POST", path)
        return model.model_validate_json(response.content)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        json: object | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx2.Response:
        response = self._http.request(
            method,
            path,
            params=params,
            json=json,
            content=content,
            headers=headers,
        )
        if response.status_code == 404:
            raise DaemonNotFoundError(_error_detail(response), response=response)
        if response.status_code == 409:
            raise DaemonConflictError(_error_detail(response), response=response)
        if response.status_code == 503:
            raise DaemonUnavailableError(_error_detail(response), response=response)
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
    "DaemonUnavailableError",
]

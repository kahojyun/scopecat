"""Typed wire contracts shared by daemon servers and Python clients.

The models contain durable data only. In particular, execution keeps
``RunProgram`` and its Python closures in the client process.
"""

from __future__ import annotations

from base64 import b64decode, b64encode
from binascii import Error as BinasciiError
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from scopecat.analysis.datasets import DerivedDatasetPayload
from scopecat.config.inventory import InstrumentInventoryChange
from scopecat.config.parameter_updates import ParameterUpdate
from scopecat.config.registry.records import (
    ConfigRegistryActivationRecord,
    ConfigRegistryEntry,
)
from scopecat.control.models import RunPlanSummary
from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.problems import Problem
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.records.analysis import (
    MAX_ANALYSIS_OUTPUTS,
    AnalysisExecution,
    AnalysisExecutionOutputReference,
    AnalysisFact,
    AnalysisFigureView,
    AnalysisTableView,
    validate_analysis_output_content_budget,
)
from scopecat.records.artifact import RunContentEntry, Sha256ContentHash
from scopecat.records.config import (
    ConfigContentHash,
    ConfigProfileSnapshot,
    InstrumentBindingSpec,
)
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetHeader,
    MeasurementDatasetSeal,
)
from scopecat.records.parameter_change import (
    ParameterChangeProposal,
    ParameterValueDelta,
)
from scopecat.records.run import (
    RunConfigSource,
    RunManifest,
)
from scopecat.records.run_request import RunRequest
from scopecat.sdk.instruments.contracts import InstrumentDescription
from scopecat.sdk.instruments.execution import RunHardwareBatch

type NonEmptyText = Annotated[str, Field(min_length=1)]


class _WireModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class ConfigDraftCommand(_WireModel):
    """Typed parameter edits against one observed active registry generation."""

    base_entry_id: NonEmptyText
    base_content_hash: ConfigContentHash
    base_generation: int = Field(ge=1)
    candidate_id: NonEmptyText
    updates: tuple[ParameterUpdate, ...] = Field(min_length=1)


class DirectConfigRevisionSource(_WireModel):
    kind: Literal["direct_config_profile"] = "direct_config_profile"
    config: ConfigProfileSnapshot


class ManualConfigDraftRevisionSource(_WireModel):
    kind: Literal["manual_parameter_updates"] = "manual_parameter_updates"
    draft: ConfigDraftCommand
    expected_result_content_hash: ConfigContentHash


class CandidateConfigRevisionSource(_WireModel):
    kind: Literal["candidate_config"] = "candidate_config"
    run_id: NonEmptyText
    proposal_id: NonEmptyText


type ConfigRevisionSource = Annotated[
    DirectConfigRevisionSource
    | ManualConfigDraftRevisionSource
    | CandidateConfigRevisionSource,
    Field(discriminator="kind"),
]


class ConfigPublishCommand(_WireModel):
    """Validate, save, and select one revision in a single transaction."""

    source: ConfigRevisionSource
    actor: NonEmptyText
    expected_generation: int = Field(ge=0)
    entry_id: NonEmptyText | None = None
    note: str = ""

    @model_validator(mode="after")
    def validate_entry_id(self) -> ConfigPublishCommand:
        if self.entry_id is None and not isinstance(
            self.source, CandidateConfigRevisionSource
        ):
            raise ValueError("direct and draft revisions require an entry id")
        return self


class ConfigPublishReceipt(_WireModel):
    entry: ConfigRegistryEntry
    deltas: tuple[ParameterValueDelta, ...] = ()
    activation: ConfigRegistryActivationRecord


class InstrumentInventoryMigrationCommand(_WireModel):
    """Publish a complete config through an explicitly drained migration."""

    config: ConfigProfileSnapshot
    entry_id: NonEmptyText
    changes: tuple[InstrumentInventoryChange, ...] = Field(min_length=1)
    actor: NonEmptyText
    expected_generation: int = Field(ge=1)
    note: str = ""


class InstrumentInventoryMigrationReceipt(_WireModel):
    entry: ConfigRegistryEntry
    activation: ConfigRegistryActivationRecord
    changes: tuple[InstrumentInventoryChange, ...] = Field(min_length=1)


class ConfigEntryActivationCommand(_WireModel):
    """Select a saved revision with generation compare-and-swap."""

    entry_id: NonEmptyText
    actor: NonEmptyText
    expected_generation: int = Field(ge=0)
    note: str = ""


class ConfigUndoCommand(_WireModel):
    """Restore the previous distinct entry with generation compare-and-swap."""

    actor: NonEmptyText
    expected_generation: int = Field(ge=1)
    note: str = ""


class ConfigActivationReceipt(_WireModel):
    activation: ConfigRegistryActivationRecord


class AnalysisInputPayload(_WireModel):
    """JSON-safe reference consumed by a durable analysis record."""

    target: NonEmptyText
    kind: Literal["measurement_dataset"]
    content_hash: NonEmptyText
    codec: NonEmptyText
    role: NonEmptyText
    title: str | None = None
    metadata: dict[str, JsonValue] | None = None


class AnalysisTableOutputPayload(_WireModel):
    kind: Literal["table"]
    id: NonEmptyText
    title: NonEmptyText
    content: AnalysisTableView
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class AnalysisFactOutputPayload(_WireModel):
    kind: Literal["fact"]
    id: NonEmptyText
    title: NonEmptyText
    content: AnalysisFact
    produced_by: AnalysisExecutionOutputReference | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class AnalysisDatasetOutputPayload(_WireModel):
    kind: Literal["dataset"]
    id: NonEmptyText
    title: NonEmptyText
    content: DerivedDatasetPayload
    produced_by: AnalysisExecutionOutputReference | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class AnalysisFigureOutputPayload(_WireModel):
    kind: Literal["figure"]
    id: NonEmptyText
    title: NonEmptyText
    content: AnalysisFigureView
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class AnalysisParameterProposalOutputPayload(_WireModel):
    kind: Literal["parameter_change_proposal"]
    id: NonEmptyText
    title: NonEmptyText
    content: ParameterChangeProposal
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class AnalysisArtifactOutputPayload(_WireModel):
    kind: Literal["artifact"]
    id: NonEmptyText
    title: NonEmptyText
    content_base64: str
    filename: NonEmptyText
    media_type: NonEmptyText
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("content_base64")
    @classmethod
    def validate_content_base64(cls, value: str) -> str:
        try:
            decoded = b64decode(value, validate=True)
        except (BinasciiError, ValueError) as error:
            raise ValueError(
                "analysis artifact content must be valid base64"
            ) from error
        if b64encode(decoded).decode("ascii") != value:
            raise ValueError("analysis artifact content must use canonical base64")
        return value

    def content_bytes(self) -> bytes:
        return b64decode(self.content_base64, validate=True)


type AnalysisOutputPayload = Annotated[
    AnalysisFactOutputPayload
    | AnalysisDatasetOutputPayload
    | AnalysisArtifactOutputPayload
    | AnalysisTableOutputPayload
    | AnalysisFigureOutputPayload
    | AnalysisParameterProposalOutputPayload,
    Field(discriminator="kind"),
]


class AnalysisSaveCommand(_WireModel):
    """Persist JSON analysis results against a daemon-owned run."""

    title: NonEmptyText
    analysis_key: NonEmptyText
    step_id: NonEmptyText | None = None
    inputs: tuple[AnalysisInputPayload, ...] = ()
    executions: tuple[AnalysisExecution, ...] = ()
    outputs: tuple[AnalysisOutputPayload, ...] = Field(
        default=(),
        max_length=MAX_ANALYSIS_OUTPUTS,
    )

    @model_validator(mode="after")
    def validate_outputs(self) -> AnalysisSaveCommand:
        validate_analysis_output_content_budget(
            output.content
            for output in self.outputs
            if isinstance(
                output, AnalysisTableOutputPayload | AnalysisFigureOutputPayload
            )
        )
        proposals = tuple(
            output.content
            for output in self.outputs
            if isinstance(output, AnalysisParameterProposalOutputPayload)
        )
        expected_analysis_record_id = f"analysis-{self.analysis_key}"
        if any(
            proposal.analysis_record_id != expected_analysis_record_id
            for proposal in proposals
        ):
            raise ValueError("analysis proposal must identify the command analysis")
        ids = tuple(proposal.id for proposal in proposals)
        if len(ids) != len(set(ids)):
            raise ValueError("analysis proposal ids must be unique")
        output_ids = tuple(output.id for output in self.outputs)
        if len(output_ids) != len(set(output_ids)):
            raise ValueError("analysis output ids must be unique")
        execution_ids = tuple(execution.id for execution in self.executions)
        if len(execution_ids) != len(set(execution_ids)):
            raise ValueError("analysis execution ids must be unique")
        materialized_outputs = tuple(
            output
            for output in self.outputs
            if isinstance(
                output,
                AnalysisFactOutputPayload | AnalysisDatasetOutputPayload,
            )
        )
        if any(
            output.produced_by is not None
            and output.produced_by.execution_id not in execution_ids
            for output in materialized_outputs
        ):
            raise ValueError("analysis output producer must identify an execution")
        execution_outputs = {
            (execution.id, output.name)
            for execution in self.executions
            for output in execution.outputs
        }
        if any(
            output.produced_by is not None
            and (
                output.produced_by.execution_id,
                output.produced_by.output_name,
            )
            not in execution_outputs
            for output in materialized_outputs
        ):
            raise ValueError(
                "analysis output producer must identify an execution output"
            )
        dataset_ids = {
            output.id
            for output in self.outputs
            if isinstance(output, AnalysisDatasetOutputPayload)
        }
        for output in self.outputs:
            if not isinstance(
                output,
                AnalysisTableOutputPayload | AnalysisFigureOutputPayload,
            ):
                continue
            source = output.content.source
            if source is not None and source.output_id not in dataset_ids:
                raise ValueError("analysis view source must identify a dataset output")
        return self


class AnalysisSaveReceipt(_WireModel):
    record: RunContentEntry
    analysis_key: NonEmptyText
    inputs: tuple[AnalysisInputPayload, ...] = ()
    parameter_proposals: tuple[ParameterChangeProposal, ...] = ()


class RunAttachmentCommand(_WireModel):
    """Ingest client-owned content without exposing a client filesystem path."""

    key: NonEmptyText
    kind: NonEmptyText = "attachment"
    text: str | None = None
    content_base64: str | None = None
    filename: NonEmptyText | None = None
    media_type: NonEmptyText | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("content_base64")
    @classmethod
    def validate_content_base64(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validated_base64(value)

    @model_validator(mode="after")
    def validate_source(self) -> RunAttachmentCommand:
        if (self.text is None) == (self.content_base64 is None):
            raise ValueError("run attachment requires exactly one content source")
        return self


class PayloadObjectReceipt(_WireModel):
    """One immutable command-payload body accepted by the daemon."""

    ref: Sha256ContentHash
    content_hash: Sha256ContentHash
    size_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_reference(self) -> PayloadObjectReceipt:
        if self.ref != self.content_hash:
            raise ValueError("payload object ref must equal its content hash")
        return self


class RunSubmission(_WireModel):
    """Admit a client-planned run while retaining executable Python in the client.

    Admission authorizes declared resources; it cannot infer work omitted by the
    client planner.
    """

    submission_id: NonEmptyText
    config: ConfigProfileSnapshot
    config_source: RunConfigSource | None = None
    request: RunRequest
    plan: RunPlanSummary

    @property
    def intent_content_hash(self) -> str:
        """Identify submission content independently of its retry key."""

        return stable_content_hash(
            self.model_dump(mode="json", exclude={"submission_id"})
        )


class RunAdmission(_WireModel):
    """Canonical run manifest returned for an idempotent submission."""

    submission_id: NonEmptyText
    manifest: RunManifest

    @property
    def run_id(self) -> str:
        return self.manifest.run_id


class ExecutorStartRequest(_WireModel):
    """Start one daemon-owned execution session."""

    executor_id: NonEmptyText


class ExecutorLease(_WireModel):
    """Renewable authority to report effects for one run."""

    lease_id: NonEmptyText
    run_id: NonEmptyText
    executor_id: NonEmptyText
    issued_at: datetime
    expires_at: datetime
    heartbeat_interval_seconds: float = Field(gt=0)
    cancellation_requested_at: datetime | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> ExecutorLease:
        issued_at = _aware_datetime(self.issued_at, field_name="issued_at")
        expires_at = _aware_datetime(self.expires_at, field_name="expires_at")
        if expires_at <= issued_at:
            raise ValueError("executor lease must expire after it is issued")
        if self.cancellation_requested_at is not None:
            _aware_datetime(
                self.cancellation_requested_at,
                field_name="cancellation_requested_at",
            )
        return self


class ExecutorHeartbeat(_WireModel):
    """Renew a lease using its unique identity as the fencing token."""

    lease_id: NonEmptyText


class _FencedCommand(_WireModel):
    lease_id: NonEmptyText


class _FencedOperationCommand(_FencedCommand):
    operation_id: NonEmptyText


class RunInstrumentProvisionCommand(_FencedOperationCommand):
    """Acquire daemon-owned instrument epochs from the admitted run snapshot."""


class RunInstrumentProvisionReceipt(_WireModel):
    """State evidence around provisioning daemon-owned run instruments.

    ``observed_state`` is read after exclusive ownership is acquired.
    ``baseline_state`` is the execution baseline after the run policy is applied.
    """

    run_id: NonEmptyText
    operation_id: NonEmptyText
    status: Literal["ready", "rejected"]
    instrument_ids: tuple[NonEmptyText, ...] = ()
    problems: tuple[Problem, ...] = ()
    observed_state: tuple[InstrumentStateSnapshot, ...] = ()
    baseline_state: tuple[InstrumentStateSnapshot, ...] = ()

    @model_validator(mode="after")
    def validate_result(self) -> RunInstrumentProvisionReceipt:
        if len(self.instrument_ids) != len(set(self.instrument_ids)):
            raise ValueError("run instrument provisioning ids must be unique")
        if self.status == "ready":
            if tuple(state.instrument_id for state in self.observed_state) != (
                self.instrument_ids
            ):
                raise ValueError(
                    "ready run observed state must match instrument ids in order"
                )
            if tuple(state.instrument_id for state in self.baseline_state) != (
                self.instrument_ids
            ):
                raise ValueError(
                    "ready run baseline state must match instrument ids in order"
                )
            if self.problems:
                raise ValueError(
                    "ready run instrument provisioning cannot contain problems"
                )
        elif not self.problems:
            raise ValueError("rejected run instrument provisioning requires a problem")
        elif self.observed_state or self.baseline_state:
            raise ValueError(
                "rejected run instrument provisioning cannot expose state evidence"
            )
        return self


class RunHardwareBatchCommand(_FencedCommand):
    batch: RunHardwareBatch


class RunHardwareFinishCommand(_FencedOperationCommand):
    failed: bool


class _ExecutionTransitionCommand(_FencedCommand):
    transition: ExecutionTransition

    @model_validator(mode="after")
    def validate_transition(self) -> _ExecutionTransitionCommand:
        if self.transition.sequence is not None:
            raise ValueError("submitted transition sequence must be daemon-assigned")
        return self


class ExecutionTransitionClaim(_ExecutionTransitionCommand):
    """Atomically claim a new effect operation before executing it."""


class ExecutionTransitionAppend(_ExecutionTransitionCommand):
    """Append one transition using its content hash as the retry identity."""


class MeasurementHeaderCommand(_FencedCommand):
    header: MeasurementDatasetHeader


class MeasurementAppendCommand(_FencedCommand):
    append: MeasurementDatasetAppend


class MeasurementSealCommand(_FencedCommand):
    seal: MeasurementDatasetSeal


class TerminalModelWrite(_WireModel):
    ref: NonEmptyText
    value: dict[str, JsonValue]


class TerminalRunCommitCommand(_FencedCommand):
    """Lossless JSON projection of one interpreter terminal delta."""

    outcome: RunOutcome
    contents: tuple[RunContentEntry, ...] = ()
    models: tuple[TerminalModelWrite, ...] = ()


class AttentionResolutionReceipt(_WireModel):
    run_id: NonEmptyText
    state: Literal["closed"]
    released_resource_count: int = Field(ge=0)


class RunCancellationReceipt(_WireModel):
    """Durable result of an idempotent operator cancellation request."""

    run_id: NonEmptyText
    status: Literal["cancel_requested", "cancelled", "not_accepted"]
    cancellation_requested_at: datetime | None = None
    outcome: RunOutcome | None = None

    @model_validator(mode="after")
    def validate_result(self) -> RunCancellationReceipt:
        if self.cancellation_requested_at is not None:
            _aware_datetime(
                self.cancellation_requested_at,
                field_name="cancellation_requested_at",
            )
        if self.status == "cancel_requested":
            if self.cancellation_requested_at is None or self.outcome is not None:
                raise ValueError(
                    "pending cancellation requires a request time and no outcome"
                )
        elif self.status == "cancelled":
            if (
                self.cancellation_requested_at is None
                or self.outcome is None
                or self.outcome.result != "cancelled"
            ):
                raise ValueError(
                    "completed cancellation requires its request and cancelled outcome"
                )
        elif self.outcome is None:
            raise ValueError(
                "non-accepted cancellation requires the existing terminal outcome"
            )
        return self


class InstrumentContractCatalogRequest(_WireModel):
    """Resolve the exact contracts advertised for one config snapshot."""

    config: ConfigProfileSnapshot


class InstrumentDriverProbeCommand(_WireModel):
    """Open, identify, and close one candidate instrument binding."""

    binding: InstrumentBindingSpec


class InstrumentDriverProbeReceipt(_WireModel):
    status: Literal["connected", "rejected"]
    description: InstrumentDescription | None = None
    problems: tuple[Problem, ...] = ()

    @model_validator(mode="after")
    def validate_outcome(self) -> InstrumentDriverProbeReceipt:
        if self.status == "connected":
            valid = self.description is not None and not self.problems
        else:
            valid = self.description is None and bool(self.problems)
        if not valid:
            raise ValueError("driver probe status and outcome disagree")
        return self


class InstrumentSessionOpenCommand(_WireModel):
    """Acquire configured instruments plus optional session-only bindings."""

    operation_id: NonEmptyText
    actor: NonEmptyText
    instrument_ids: tuple[NonEmptyText, ...] = Field(min_length=1)
    temporary_bindings: tuple[InstrumentBindingSpec, ...] = ()

    @field_validator("instrument_ids")
    @classmethod
    def validate_instrument_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("instrument session ids must be unique")
        return value

    @model_validator(mode="after")
    def validate_temporary_bindings(self) -> InstrumentSessionOpenCommand:
        binding_ids = tuple(binding.id for binding in self.temporary_bindings)
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("temporary instrument binding ids must be unique")
        unknown = tuple(
            instrument_id
            for instrument_id in binding_ids
            if instrument_id not in self.instrument_ids
        )
        if unknown:
            raise ValueError(
                "temporary bindings must belong to the opened session: "
                + ", ".join(unknown)
            )
        return self


class InstrumentSessionLeaseReceipt(_WireModel):
    session_id: NonEmptyText
    renewed_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_lease(self) -> InstrumentSessionLeaseReceipt:
        _validate_instrument_session_lease(self.renewed_at, self.expires_at)
        return self


class InstrumentSessionOpenReceipt(_WireModel):
    """Daemon-owned direct-control session opened against one config revision."""

    session_id: NonEmptyText
    actor: NonEmptyText
    config_entry_id: NonEmptyText
    config_content_hash: ConfigContentHash
    instrument_ids: tuple[NonEmptyText, ...] = Field(min_length=1)
    configured_default_instrument_ids: tuple[NonEmptyText, ...]
    descriptions: tuple[InstrumentDescription, ...]
    observed_state: tuple[InstrumentStateSnapshot, ...]
    opened_at: datetime
    renewed_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_contents(self) -> InstrumentSessionOpenReceipt:
        _aware_datetime(self.opened_at, field_name="opened_at")
        _validate_instrument_session_lease(self.renewed_at, self.expires_at)
        described_ids = tuple(
            description.instrument_id for description in self.descriptions
        )
        if described_ids != self.instrument_ids:
            raise ValueError(
                "instrument session descriptions must match instrument_ids in order"
            )
        observed_ids = tuple(state.instrument_id for state in self.observed_state)
        if observed_ids != self.instrument_ids:
            raise ValueError(
                "instrument session observed state must match instrument_ids in order"
            )
        configured = set(self.configured_default_instrument_ids)
        if self.configured_default_instrument_ids != tuple(
            instrument_id
            for instrument_id in self.instrument_ids
            if instrument_id in configured
        ):
            raise ValueError(
                "configured default ids must be an ordered subset of instrument_ids"
            )
        return self


class InstrumentConfiguredDefaultsApplyCommand(_WireModel):
    """Reconcile one session instrument with its pinned configured defaults."""

    operation_id: NonEmptyText


class InstrumentConfiguredDefaultsApplyReceipt(_WireModel):
    session_id: NonEmptyText
    operation_id: NonEmptyText
    instrument_id: NonEmptyText
    config_entry_id: NonEmptyText
    status: Literal["applied", "unchanged", "rejected"]
    problems: tuple[Problem, ...] = ()
    state: InstrumentStateSnapshot | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> InstrumentConfiguredDefaultsApplyReceipt:
        if self.status in {"applied", "unchanged"}:
            if self.problems:
                raise ValueError(
                    "successful configured-default apply cannot contain problems"
                )
            if self.state is None:
                raise ValueError(
                    "successful configured-default apply requires synchronized state"
                )
        elif not self.problems:
            raise ValueError("rejected configured-default apply requires a problem")
        elif self.state is not None:
            raise ValueError("rejected configured-default apply cannot report state")
        if self.state is not None and self.state.instrument_id != self.instrument_id:
            raise ValueError("configured-default state must match instrument_id")
        return self


class InstrumentSessionEndReceipt(_WireModel):
    session_id: NonEmptyText
    status: Literal["closed", "aborted"]


def _aware_datetime(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value


def _validate_instrument_session_lease(
    renewed_at: datetime,
    expires_at: datetime,
) -> None:
    renewed_at = _aware_datetime(renewed_at, field_name="renewed_at")
    expires_at = _aware_datetime(expires_at, field_name="expires_at")
    if expires_at <= renewed_at:
        raise ValueError("expires_at must follow renewed_at")


def _validated_base64(value: str) -> str:
    try:
        b64decode(value, validate=True)
    except (BinasciiError, ValueError) as error:
        raise ValueError("content_base64 must be valid base64") from error
    return value


__all__ = [
    "AnalysisArtifactOutputPayload",
    "AnalysisDatasetOutputPayload",
    "AnalysisFactOutputPayload",
    "AnalysisFigureOutputPayload",
    "AnalysisInputPayload",
    "AnalysisOutputPayload",
    "AnalysisParameterProposalOutputPayload",
    "AnalysisSaveCommand",
    "AnalysisSaveReceipt",
    "AnalysisTableOutputPayload",
    "AttentionResolutionReceipt",
    "CandidateConfigRevisionSource",
    "ConfigActivationReceipt",
    "ConfigDraftCommand",
    "ConfigEntryActivationCommand",
    "ConfigPublishCommand",
    "ConfigPublishReceipt",
    "ConfigRevisionSource",
    "ConfigUndoCommand",
    "DirectConfigRevisionSource",
    "ExecutionTransitionAppend",
    "ExecutionTransitionClaim",
    "ExecutorHeartbeat",
    "ExecutorLease",
    "ExecutorStartRequest",
    "InstrumentConfiguredDefaultsApplyCommand",
    "InstrumentConfiguredDefaultsApplyReceipt",
    "InstrumentContractCatalogRequest",
    "InstrumentDriverProbeCommand",
    "InstrumentDriverProbeReceipt",
    "InstrumentInventoryMigrationCommand",
    "InstrumentInventoryMigrationReceipt",
    "InstrumentSessionEndReceipt",
    "InstrumentSessionLeaseReceipt",
    "InstrumentSessionOpenCommand",
    "InstrumentSessionOpenReceipt",
    "ManualConfigDraftRevisionSource",
    "MeasurementAppendCommand",
    "MeasurementHeaderCommand",
    "MeasurementSealCommand",
    "PayloadObjectReceipt",
    "RunAdmission",
    "RunAttachmentCommand",
    "RunCancellationReceipt",
    "RunInstrumentProvisionCommand",
    "RunInstrumentProvisionReceipt",
    "RunSubmission",
    "TerminalModelWrite",
    "TerminalRunCommitCommand",
]

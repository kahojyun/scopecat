"""Typed wire contracts shared by daemon servers and Python clients.

The models contain durable data only. In particular, execution keeps
``RunProgram`` and its Python closures in the client process.
"""

from __future__ import annotations

from base64 import b64decode
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

from scopecat.config.parameter_updates import ParameterUpdate
from scopecat.config.registry.records import (
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
)
from scopecat.control.models import RunPlanSummary
from scopecat.kernel.content_identity import stable_content_hash
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import (
    ConfigContentHash,
    ConfigProfileSnapshot,
)
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetSeal,
)
from scopecat.records.parameter_change import (
    ParameterChangeDecisionAuthority,
    ParameterChangeProposal,
    ParameterChangeReviewState,
    ParameterValueDelta,
)
from scopecat.records.run import RunConfigSource, RunManifest, RunOutcome
from scopecat.records.run_request import RunRequest

type NonEmptyText = Annotated[str, Field(min_length=1)]


class _WireModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        allow_inf_nan=False,
    )


class DirectConfigImportCommand(_WireModel):
    """Import one direct configuration snapshot into the daemon registry."""

    entry_id: NonEmptyText
    config: ConfigProfileSnapshot
    registered_by: NonEmptyText
    note: str = ""


class DirectConfigDefaultCommand(_WireModel):
    """Atomically save one direct snapshot and select it as the default."""

    entry_id: NonEmptyText
    config: ConfigProfileSnapshot
    registered_by: NonEmptyText
    operator: NonEmptyText
    expected_generation: int = Field(ge=0)
    note: str = ""


class ConfigDefaultReceipt(_WireModel):
    entry: ConfigRegistryEntry
    active_state: ConfigRegistryActiveState
    activation: ConfigRegistryActivationRecord

    @model_validator(mode="after")
    def validate_activation(self) -> ConfigDefaultReceipt:
        if (
            self.entry.id != self.activation.entry_id
            or self.entry.content_hash != self.activation.entry_content_hash
            or self.active_state.history[-1] != self.activation
        ):
            raise ValueError("config default receipt identity is inconsistent")
        return self


class ConfigDraftCommand(_WireModel):
    """Typed parameter edits against one observed active registry generation."""

    base_entry_id: NonEmptyText
    base_content_hash: ConfigContentHash
    base_generation: int = Field(ge=1)
    candidate_id: NonEmptyText
    updates: tuple[ParameterUpdate, ...] = Field(min_length=1)


class ConfigDraftRegistrationCommand(_WireModel):
    """Register a revalidated draft without changing the active entry."""

    draft: ConfigDraftCommand
    expected_result_content_hash: ConfigContentHash
    entry_id: NonEmptyText
    registered_by: NonEmptyText
    note: str = ""


class ConfigDraftRegistrationReceipt(_WireModel):
    entry: ConfigRegistryEntry
    result_content_hash: ConfigContentHash
    deltas: tuple[ParameterValueDelta, ...] = Field(min_length=1)


class ConfigDraftDefaultCommand(_WireModel):
    """Register a reviewed draft and select it as the default in one transaction."""

    registration: ConfigDraftRegistrationCommand
    operator: NonEmptyText
    activation_note: str | None = None


class ConfigDraftDefaultReceipt(_WireModel):
    entry: ConfigRegistryEntry
    result_content_hash: ConfigContentHash
    deltas: tuple[ParameterValueDelta, ...] = Field(min_length=1)
    active_state: ConfigRegistryActiveState
    activation: ConfigRegistryActivationRecord

    @model_validator(mode="after")
    def validate_activation(self) -> ConfigDraftDefaultReceipt:
        if (
            self.entry.content_hash != self.result_content_hash
            or self.entry.id != self.activation.entry_id
            or self.entry.content_hash != self.activation.entry_content_hash
            or self.active_state.history[-1] != self.activation
        ):
            raise ValueError("config draft default receipt identity is inconsistent")
        return self


class ConfigEntryActivationCommand(_WireModel):
    """Select a registered entry with generation compare-and-swap."""

    entry_id: NonEmptyText
    operator: NonEmptyText
    expected_generation: int = Field(ge=0)
    note: str = ""


class ConfigRollbackCommand(_WireModel):
    """Restore the previous distinct entry with generation compare-and-swap."""

    operator: NonEmptyText
    expected_generation: int = Field(ge=1)
    note: str = ""


class ConfigActivationReceipt(_WireModel):
    active_state: ConfigRegistryActiveState
    activation: ConfigRegistryActivationRecord

    @model_validator(mode="after")
    def validate_activation(self) -> ConfigActivationReceipt:
        if self.active_state.history[-1] != self.activation:
            raise ValueError("config activation receipt must contain the history head")
        return self


class AnalysisInputPayload(_WireModel):
    """JSON-safe reference consumed by a durable analysis record."""

    target: NonEmptyText
    kind: Literal["artifact", "dataset", "uri"]
    role: NonEmptyText
    title: str | None = None
    metadata: dict[str, JsonValue] | None = None


class AnalysisNoteOutputPayload(_WireModel):
    kind: Literal["note"]
    title: NonEmptyText
    content: NonEmptyText
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class AnalysisJsonOutputPayload(_WireModel):
    kind: Literal["table", "array", "figure"]
    title: NonEmptyText
    content: JsonValue
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class AnalysisArtifactOutputPayload(_WireModel):
    """One binary analysis artifact encoded for JSON transport."""

    kind: Literal["artifact"]
    title: NonEmptyText
    artifact_kind: NonEmptyText
    content_base64: str
    artifact_id: NonEmptyText | None = None
    filename: NonEmptyText
    media_type: NonEmptyText
    artifact_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("content_base64")
    @classmethod
    def validate_content_base64(cls, value: str) -> str:
        return _validated_base64(value)


class AnalysisParameterProposalOutputPayload(_WireModel):
    kind: Literal["parameter_change_proposal"]
    title: NonEmptyText
    content: ParameterChangeProposal
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


type AnalysisOutputPayload = Annotated[
    AnalysisArtifactOutputPayload
    | AnalysisNoteOutputPayload
    | AnalysisJsonOutputPayload
    | AnalysisParameterProposalOutputPayload,
    Field(discriminator="kind"),
]


class AnalysisSaveCommand(_WireModel):
    """Persist JSON analysis results against a daemon-owned run."""

    title: NonEmptyText
    analysis_key: NonEmptyText
    step_id: NonEmptyText | None = None
    inputs: tuple[AnalysisInputPayload, ...] = ()
    outputs: tuple[AnalysisOutputPayload, ...] = ()

    @model_validator(mode="after")
    def validate_proposals(self) -> AnalysisSaveCommand:
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
        return self


class AnalysisSaveReceipt(_WireModel):
    record: RunContentEntry
    analysis_key: NonEmptyText
    inputs: tuple[AnalysisInputPayload, ...] = ()
    output_artifacts: tuple[RunContentEntry, ...] = ()


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


class ParameterProposalReviewCommand(_WireModel):
    decision: ParameterChangeReviewState
    reviewer: NonEmptyText
    note: str = ""


class ParameterProposalDecisionCommand(_WireModel):
    decision: ParameterChangeReviewState
    authority: ParameterChangeDecisionAuthority
    note: str = ""


class CandidateConfigActivationCommand(_WireModel):
    """Build, register, and activate config from durable approved proposals."""

    run_id: NonEmptyText
    proposal_ids: tuple[NonEmptyText, ...] = Field(min_length=1)
    entry_id: NonEmptyText | None = None
    registered_by: NonEmptyText
    operator: NonEmptyText
    expected_generation: int = Field(ge=0)
    note: str = ""
    activation_note: str | None = None

    @field_validator("proposal_ids")
    @classmethod
    def validate_proposal_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("candidate proposal ids must be unique")
        return value


class CandidateConfigActivationReceipt(_WireModel):
    entry: ConfigRegistryEntry
    active_state: ConfigRegistryActiveState
    activation: ConfigRegistryActivationRecord

    @model_validator(mode="after")
    def validate_activation(self) -> CandidateConfigActivationReceipt:
        if (
            self.entry.id != self.activation.entry_id
            or self.entry.content_hash != self.activation.entry_content_hash
            or self.active_state.history[-1] != self.activation
        ):
            raise ValueError("candidate activation receipt identity is inconsistent")
        return self


class RunSubmission(_WireModel):
    """Admit a plan while retaining its executable Python in the client."""

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

    @model_validator(mode="after")
    def validate_interval(self) -> ExecutorLease:
        issued_at = _aware_datetime(self.issued_at, field_name="issued_at")
        expires_at = _aware_datetime(self.expires_at, field_name="expires_at")
        if expires_at <= issued_at:
            raise ValueError("executor lease must expire after it is issued")
        return self


class ExecutorHeartbeat(_WireModel):
    """Renew a lease using its unique identity as the fencing token."""

    lease_id: NonEmptyText


class _FencedCommand(_WireModel):
    lease_id: NonEmptyText


class ExecutionTransitionAppend(_FencedCommand):
    """Append one transition using its content hash as the retry identity."""

    transition: ExecutionTransition

    @model_validator(mode="after")
    def validate_transition(self) -> ExecutionTransitionAppend:
        if self.transition.sequence is not None:
            raise ValueError("submitted transition sequence must be daemon-assigned")
        return self


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


def _aware_datetime(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value


def _validated_base64(value: str) -> str:
    try:
        b64decode(value, validate=True)
    except (BinasciiError, ValueError) as error:
        raise ValueError("content_base64 must be valid base64") from error
    return value


__all__ = [
    "AnalysisArtifactOutputPayload",
    "AnalysisInputPayload",
    "AnalysisJsonOutputPayload",
    "AnalysisNoteOutputPayload",
    "AnalysisOutputPayload",
    "AnalysisParameterProposalOutputPayload",
    "AnalysisSaveCommand",
    "AnalysisSaveReceipt",
    "AttentionResolutionReceipt",
    "CandidateConfigActivationCommand",
    "CandidateConfigActivationReceipt",
    "ConfigActivationReceipt",
    "ConfigDefaultReceipt",
    "ConfigDraftCommand",
    "ConfigDraftDefaultCommand",
    "ConfigDraftDefaultReceipt",
    "ConfigDraftRegistrationCommand",
    "ConfigDraftRegistrationReceipt",
    "ConfigEntryActivationCommand",
    "ConfigRollbackCommand",
    "DirectConfigDefaultCommand",
    "DirectConfigImportCommand",
    "ExecutionTransitionAppend",
    "ExecutorHeartbeat",
    "ExecutorLease",
    "ExecutorStartRequest",
    "MeasurementAppendCommand",
    "MeasurementSealCommand",
    "ParameterProposalDecisionCommand",
    "ParameterProposalReviewCommand",
    "RunAdmission",
    "RunAttachmentCommand",
    "RunSubmission",
    "TerminalModelWrite",
    "TerminalRunCommitCommand",
]

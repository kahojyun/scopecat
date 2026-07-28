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
    ConfigRegistryEntry,
)
from scopecat.control.models import RunPlanSummary
from scopecat.execution.ports.instruments import RunHardwareBatch
from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.problems import Problem
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.records.artifact import RunContentEntry, Sha256ContentHash
from scopecat.records.config import (
    ConfigContentHash,
    ConfigProfileSnapshot,
)
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
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
    role: NonEmptyText
    title: str | None = None
    metadata: dict[str, JsonValue] | None = None


class AnalysisJsonOutputPayload(_WireModel):
    kind: Literal["table", "figure"]
    title: NonEmptyText
    content: JsonValue
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class AnalysisParameterProposalOutputPayload(_WireModel):
    kind: Literal["parameter_change_proposal"]
    title: NonEmptyText
    content: ParameterChangeProposal
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


type AnalysisOutputPayload = Annotated[
    AnalysisJsonOutputPayload | AnalysisParameterProposalOutputPayload,
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


class _FencedOperationCommand(_FencedCommand):
    operation_id: NonEmptyText


class RunInstrumentProvisionCommand(_FencedOperationCommand):
    """Acquire daemon-owned instrument epochs from the admitted run snapshot."""


class RunInstrumentProvisionReceipt(_WireModel):
    """State evidence around run preparation for daemon-owned instruments.

    ``observed_state`` is read after exclusive ownership is acquired.
    ``prepared_state`` is the execution baseline after the run policy is applied.
    """

    run_id: NonEmptyText
    operation_id: NonEmptyText
    status: Literal["ready", "rejected"]
    instrument_ids: tuple[NonEmptyText, ...] = ()
    problems: tuple[Problem, ...] = ()
    observed_state: tuple[InstrumentStateSnapshot, ...] = ()
    prepared_state: tuple[InstrumentStateSnapshot, ...] = ()

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
            if tuple(state.instrument_id for state in self.prepared_state) != (
                self.instrument_ids
            ):
                raise ValueError(
                    "ready run prepared state must match instrument ids in order"
                )
            if self.problems:
                raise ValueError(
                    "ready run instrument provisioning cannot contain problems"
                )
        elif not self.problems:
            raise ValueError("rejected run instrument provisioning requires a problem")
        elif self.observed_state or self.prepared_state:
            raise ValueError(
                "rejected run instrument provisioning cannot expose state evidence"
            )
        return self


class RunHardwareBatchCommand(_FencedCommand):
    batch: RunHardwareBatch


class RunHardwareFinishCommand(_FencedOperationCommand):
    failed: bool


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


class InstrumentSessionOpenCommand(_WireModel):
    """Acquire and synchronize instruments against the active config."""

    operation_id: NonEmptyText
    actor: NonEmptyText
    instrument_ids: tuple[NonEmptyText, ...] = Field(min_length=1)

    @field_validator("instrument_ids")
    @classmethod
    def validate_instrument_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("instrument session ids must be unique")
        return value


class InstrumentSessionOpenReceipt(_WireModel):
    """Daemon-owned direct-control session opened against one config revision."""

    session_id: NonEmptyText
    actor: NonEmptyText
    config_entry_id: NonEmptyText
    config_content_hash: ConfigContentHash
    instrument_ids: tuple[NonEmptyText, ...] = Field(min_length=1)
    descriptions: tuple[InstrumentDescription, ...]
    opened_at: datetime

    @model_validator(mode="after")
    def validate_descriptions(self) -> InstrumentSessionOpenReceipt:
        _aware_datetime(self.opened_at, field_name="opened_at")
        described_ids = tuple(
            description.instrument_id for description in self.descriptions
        )
        if described_ids != self.instrument_ids:
            raise ValueError(
                "instrument session descriptions must match instrument_ids in order"
            )
        return self


class InstrumentSessionEndReceipt(_WireModel):
    session_id: NonEmptyText
    status: Literal["closed", "aborted"]


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
    "AnalysisInputPayload",
    "AnalysisJsonOutputPayload",
    "AnalysisOutputPayload",
    "AnalysisParameterProposalOutputPayload",
    "AnalysisSaveCommand",
    "AnalysisSaveReceipt",
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
    "ExecutorHeartbeat",
    "ExecutorLease",
    "ExecutorStartRequest",
    "InstrumentSessionEndReceipt",
    "InstrumentSessionOpenCommand",
    "InstrumentSessionOpenReceipt",
    "ManualConfigDraftRevisionSource",
    "MeasurementAppendCommand",
    "MeasurementSealCommand",
    "PayloadObjectReceipt",
    "RunAdmission",
    "RunAttachmentCommand",
    "RunInstrumentProvisionCommand",
    "RunInstrumentProvisionReceipt",
    "RunSubmission",
    "TerminalModelWrite",
    "TerminalRunCommitCommand",
]

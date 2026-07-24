"""Versioned wire contracts shared by daemon servers and Python clients.

The models contain durable data only. In particular, delegated execution keeps
``RunProgram`` and its Python closures in the executor process.
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

from scopecat.config.registry.records import (
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
)
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import (
    ConfigContentHash,
    ConfigProfileSnapshot,
    config_content_hash,
)
from scopecat.records.execution_journal import (
    CollectionChunk,
    CollectionChunkReceipt,
    CommittedPayloadEvidence,
    ExecutionTransition,
    PayloadEvidence,
)
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetAppendIndex,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
)
from scopecat.records.parameter_change import (
    ParameterChangeDecisionRecord,
    ParameterChangeProposal,
    ParameterChangeReviewState,
)
from scopecat.records.run import RunManifest
from scopecat.records.run_request import RunRequest

type NonEmptyText = Annotated[str, Field(min_length=1)]
type ExecutionMode = Literal["managed", "delegated"]
type ResourceClaimKind = Literal["target", "instrument", "channel", "group"]
type AttentionResolutionAction = Literal["release", "requeue", "abort"]


class _WireModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        allow_inf_nan=False,
    )


class RegisteredExperimentDescriptor(_WireModel):
    """Public catalog metadata for one explicitly versioned registration."""

    schema_version: Literal["scopecat.registered_experiment.v1"] = (
        "scopecat.registered_experiment.v1"
    )
    id: NonEmptyText
    version: NonEmptyText
    experiment_kind: NonEmptyText
    title: NonEmptyText | None = None
    description: str | None = None
    input_schema: dict[str, JsonValue] = Field(default_factory=dict)
    tags: tuple[NonEmptyText, ...] = ()

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("registered experiment tags must be unique")
        return value


class ExperimentCatalog(_WireModel):
    """A complete catalog snapshot addressable by an opaque revision."""

    schema_version: Literal["scopecat.experiment_catalog.v1"] = (
        "scopecat.experiment_catalog.v1"
    )
    revision: NonEmptyText
    experiments: tuple[RegisteredExperimentDescriptor, ...] = ()

    @field_validator("experiments")
    @classmethod
    def validate_registrations(
        cls,
        value: tuple[RegisteredExperimentDescriptor, ...],
    ) -> tuple[RegisteredExperimentDescriptor, ...]:
        identities = tuple((item.id, item.version) for item in value)
        if len(identities) != len(set(identities)):
            raise ValueError("catalog experiment id and version pairs must be unique")
        return value


class DirectConfigImportCommand(_WireModel):
    """Import one direct configuration snapshot into the daemon registry."""

    schema_version: Literal["scopecat.direct_config_import_command.v1"] = (
        "scopecat.direct_config_import_command.v1"
    )
    entry_id: NonEmptyText
    config: ConfigProfileSnapshot
    registered_by: NonEmptyText
    note: str = ""


class ConfigImportReceipt(_WireModel):
    schema_version: Literal["scopecat.config_import_receipt.v1"] = (
        "scopecat.config_import_receipt.v1"
    )
    entry: ConfigRegistryEntry


class ConfigEntryActivationCommand(_WireModel):
    """Select a registered entry with generation compare-and-swap."""

    schema_version: Literal["scopecat.config_entry_activation_command.v1"] = (
        "scopecat.config_entry_activation_command.v1"
    )
    entry_id: NonEmptyText
    operator: NonEmptyText
    expected_generation: int = Field(ge=0)
    note: str = ""


class ConfigRollbackCommand(_WireModel):
    """Restore the previous distinct entry with generation compare-and-swap."""

    schema_version: Literal["scopecat.config_rollback_command.v1"] = (
        "scopecat.config_rollback_command.v1"
    )
    operator: NonEmptyText
    expected_generation: int = Field(ge=1)
    note: str = ""


class ConfigActivationReceipt(_WireModel):
    schema_version: Literal["scopecat.config_activation_receipt.v1"] = (
        "scopecat.config_activation_receipt.v1"
    )
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
    filename: NonEmptyText | None = None
    media_type: NonEmptyText | None = None
    source_default_filename: NonEmptyText | None = None
    source_default_extension: str = ".bin"
    source_default_media_type: NonEmptyText = "application/octet-stream"
    source_content_hash: NonEmptyText | None = None
    artifact_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("content_base64")
    @classmethod
    def validate_content_base64(cls, value: str) -> str:
        return _validated_base64(value)

    @field_validator("source_default_extension")
    @classmethod
    def validate_source_default_extension(cls, value: str) -> str:
        if value and (
            not value.startswith(".") or "/" in value or "\\" in value or ".." in value
        ):
            raise ValueError("source_default_extension must be empty or a suffix")
        return value


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

    schema_version: Literal["scopecat.analysis_save_command.v1"] = (
        "scopecat.analysis_save_command.v1"
    )
    run_id: NonEmptyText
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
        if any(proposal.source_run_id != self.run_id for proposal in proposals):
            raise ValueError("analysis proposal must belong to the command run")
        ids = tuple(proposal.id for proposal in proposals)
        if len(ids) != len(set(ids)):
            raise ValueError("analysis proposal ids must be unique")
        return self


class AnalysisSaveReceipt(_WireModel):
    schema_version: Literal["scopecat.analysis_save_receipt.v1"] = (
        "scopecat.analysis_save_receipt.v1"
    )
    record: RunContentEntry
    analysis_key: NonEmptyText
    inputs: tuple[AnalysisInputPayload, ...] = ()
    output_artifacts: tuple[RunContentEntry, ...] = ()


class RunAttachmentCommand(_WireModel):
    """Ingest client-owned content without exposing a client filesystem path."""

    schema_version: Literal["scopecat.run_attachment_command.v1"] = (
        "scopecat.run_attachment_command.v1"
    )
    run_id: NonEmptyText
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


class RunAttachmentReceipt(_WireModel):
    schema_version: Literal["scopecat.run_attachment_receipt.v1"] = (
        "scopecat.run_attachment_receipt.v1"
    )
    run_id: NonEmptyText
    artifact: RunContentEntry

    @model_validator(mode="after")
    def validate_artifact(self) -> RunAttachmentReceipt:
        if self.artifact.role != "artifact":
            raise ValueError("run attachment receipt requires an artifact")
        return self


class ParameterProposalReviewCommand(_WireModel):
    schema_version: Literal["scopecat.parameter_proposal_review_command.v1"] = (
        "scopecat.parameter_proposal_review_command.v1"
    )
    run_id: NonEmptyText
    proposal_id: NonEmptyText
    decision: ParameterChangeReviewState
    reviewer: NonEmptyText
    note: str = ""


class ParameterProposalReviewReceipt(_WireModel):
    schema_version: Literal["scopecat.parameter_proposal_review_receipt.v1"] = (
        "scopecat.parameter_proposal_review_receipt.v1"
    )
    decision: ParameterChangeDecisionRecord


class CandidateConfigActivationCommand(_WireModel):
    """Build, register, and activate config from durable approved proposals."""

    schema_version: Literal["scopecat.candidate_config_activation_command.v1"] = (
        "scopecat.candidate_config_activation_command.v1"
    )
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
    schema_version: Literal["scopecat.candidate_config_activation_receipt.v1"] = (
        "scopecat.candidate_config_activation_receipt.v1"
    )
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


class ResourceClaimDescriptor(_WireModel):
    """JSON projection of a physical resource claim."""

    id: NonEmptyText
    kind: ResourceClaimKind = "instrument"


class DelegatedPlanSummary(_WireModel):
    """Bounded scheduling and presentation facts for an in-process plan."""

    schema_version: Literal["scopecat.delegated_plan_summary.v1"] = (
        "scopecat.delegated_plan_summary.v1"
    )
    experiment_id: NonEmptyText
    experiment_kind: NonEmptyText
    point_count: int = Field(ge=0)
    coordinate_ids: tuple[NonEmptyText, ...] = ()
    record_ids: tuple[NonEmptyText, ...] = ()
    run_resource_claims: tuple[ResourceClaimDescriptor, ...] = ()

    @field_validator("coordinate_ids", "record_ids")
    @classmethod
    def validate_unique_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("delegated plan summary ids must be unique")
        return value

    @field_validator("run_resource_claims")
    @classmethod
    def validate_unique_claims(
        cls,
        value: tuple[ResourceClaimDescriptor, ...],
    ) -> tuple[ResourceClaimDescriptor, ...]:
        identities = tuple((claim.kind, claim.id) for claim in value)
        if len(identities) != len(set(identities)):
            raise ValueError("delegated plan resource claims must be unique")
        return value


class ManagedRunSubmission(_WireModel):
    """Request that the daemon build and execute a registered experiment."""

    schema_version: Literal["scopecat.managed_run_submission.v1"] = (
        "scopecat.managed_run_submission.v1"
    )
    execution_mode: Literal["managed"] = "managed"
    submission_id: NonEmptyText
    registration_id: NonEmptyText
    registration_version: NonEmptyText
    request: RunRequest


class DelegatedRunSubmission(_WireModel):
    """Admit a scratch plan while retaining its executable Python locally."""

    schema_version: Literal["scopecat.delegated_run_submission.v1"] = (
        "scopecat.delegated_run_submission.v1"
    )
    execution_mode: Literal["delegated"] = "delegated"
    submission_id: NonEmptyText
    executor_id: NonEmptyText
    config: ConfigProfileSnapshot
    request: RunRequest
    plan: DelegatedPlanSummary

    @property
    def config_content_hash(self) -> ConfigContentHash:
        return config_content_hash(self.config)


type RunSubmission = Annotated[
    ManagedRunSubmission | DelegatedRunSubmission,
    Field(discriminator="execution_mode"),
]


class RunAdmission(_WireModel):
    """Identity returned after admission and its event commit are durable."""

    schema_version: Literal["scopecat.run_admission.v1"] = "scopecat.run_admission.v1"
    run_id: NonEmptyText
    submission_id: NonEmptyText
    execution_mode: ExecutionMode
    config_content_hash: ConfigContentHash
    accepted_at: datetime
    event_cursor: int = Field(ge=1)

    @field_validator("accepted_at")
    @classmethod
    def validate_accepted_at(cls, value: datetime) -> datetime:
        return _aware_datetime(value, field_name="accepted_at")


class ExecutorStartRequest(_WireModel):
    """Publish the running manifest and fence one delegated executor."""

    schema_version: Literal["scopecat.executor_start_request.v1"] = (
        "scopecat.executor_start_request.v1"
    )
    run_id: NonEmptyText
    executor_id: NonEmptyText
    manifest: RunManifest

    @model_validator(mode="after")
    def validate_manifest(self) -> ExecutorStartRequest:
        if self.manifest.run_id != self.run_id:
            raise ValueError("executor start and manifest run ids must match")
        if self.manifest.lifecycle != "running":
            raise ValueError("executor start requires a running manifest")
        return self


class ExecutorLease(_WireModel):
    """Renewable authority to report effects for one delegated run."""

    schema_version: Literal["scopecat.executor_lease.v1"] = "scopecat.executor_lease.v1"
    lease_id: NonEmptyText
    generation: int = Field(ge=1)
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
    """Renew a lease using its generation as the fencing token."""

    schema_version: Literal["scopecat.executor_heartbeat.v1"] = (
        "scopecat.executor_heartbeat.v1"
    )
    run_id: NonEmptyText
    lease_id: NonEmptyText
    generation: int = Field(ge=1)


class _FencedRunCommand(_WireModel):
    run_id: NonEmptyText
    lease_id: NonEmptyText
    generation: int = Field(ge=1)


class ExecutionTransitionBatch(_FencedRunCommand):
    """Idempotent delegated journal append.

    ``batch_id`` deduplicates a transport retry. Journal sequence numbers stay
    daemon-owned and therefore must be absent from submitted transitions.
    """

    schema_version: Literal["scopecat.execution_transition_batch.v1"] = (
        "scopecat.execution_transition_batch.v1"
    )
    batch_id: NonEmptyText
    lease_id: NonEmptyText
    generation: int = Field(ge=1)
    run_id: NonEmptyText
    transitions: tuple[ExecutionTransition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_transitions(self) -> ExecutionTransitionBatch:
        if any(item.run_id != self.run_id for item in self.transitions):
            raise ValueError("transition batch and transition run ids must match")
        if any(item.sequence is not None for item in self.transitions):
            raise ValueError("submitted transition sequence must be daemon-assigned")
        return self


class ExecutionTransitionBatchReceipt(_WireModel):
    """Committed journal identities returned for one transition batch."""

    schema_version: Literal["scopecat.execution_transition_batch_receipt.v1"] = (
        "scopecat.execution_transition_batch_receipt.v1"
    )
    batch_id: NonEmptyText
    committed: tuple[ExecutionTransition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_committed_transitions(self) -> ExecutionTransitionBatchReceipt:
        sequences = tuple(item.sequence for item in self.committed)
        if any(sequence is None for sequence in sequences):
            raise ValueError("committed transition sequence must be assigned")
        assigned = tuple(sequence for sequence in sequences if sequence is not None)
        if assigned != tuple(range(assigned[0], assigned[0] + len(assigned))):
            raise ValueError("committed transition sequences must be contiguous")
        run_ids = {item.run_id for item in self.committed}
        if len(run_ids) != 1:
            raise ValueError("committed transition batch must belong to one run")
        return self


class ExecutionRecoveryRequest(_FencedRunCommand):
    """Read the canonical recovery views behind all delegated ports."""

    schema_version: Literal["scopecat.execution_recovery_request.v1"] = (
        "scopecat.execution_recovery_request.v1"
    )


class ExecutionRecoverySnapshot(_WireModel):
    schema_version: Literal["scopecat.execution_recovery_snapshot.v1"] = (
        "scopecat.execution_recovery_snapshot.v1"
    )
    transitions: tuple[ExecutionTransition, ...] = ()
    measurements: tuple[MeasurementRecord, ...] = ()
    measurement_append_indices: tuple[MeasurementDatasetAppendIndex, ...] = ()
    collection_receipts: tuple[CollectionChunkReceipt, ...] = ()

    @field_validator("transitions")
    @classmethod
    def validate_committed_transitions(
        cls,
        value: tuple[ExecutionTransition, ...],
    ) -> tuple[ExecutionTransition, ...]:
        if any(item.sequence is None for item in value):
            raise ValueError("recovery transitions must have committed sequences")
        return value


class MeasurementAppendCommand(_FencedRunCommand):
    schema_version: Literal["scopecat.measurement_append_command.v1"] = (
        "scopecat.measurement_append_command.v1"
    )
    command_id: NonEmptyText
    append: MeasurementDatasetAppend

    @model_validator(mode="after")
    def validate_append(self) -> MeasurementAppendCommand:
        if self.append.run_id != self.run_id:
            raise ValueError("measurement append command run ids must match")
        if self.command_id != self.append.operation_id:
            raise ValueError("measurement append command id must match its operation")
        return self


class MeasurementAppendReceipt(_WireModel):
    schema_version: Literal["scopecat.measurement_append_receipt.v1"] = (
        "scopecat.measurement_append_receipt.v1"
    )
    command_id: NonEmptyText
    receipt: MeasurementDatasetReceipt


class MeasurementSealCommand(_FencedRunCommand):
    schema_version: Literal["scopecat.measurement_seal_command.v1"] = (
        "scopecat.measurement_seal_command.v1"
    )
    command_id: NonEmptyText
    seal: MeasurementDatasetSeal

    @model_validator(mode="after")
    def validate_seal(self) -> MeasurementSealCommand:
        if self.seal.run_id != self.run_id:
            raise ValueError("measurement seal command run ids must match")
        if self.command_id != self.seal.operation_id:
            raise ValueError("measurement seal command id must match its operation")
        return self


class MeasurementSealReceipt(_WireModel):
    schema_version: Literal["scopecat.measurement_seal_receipt.v1"] = (
        "scopecat.measurement_seal_receipt.v1"
    )
    command_id: NonEmptyText
    receipt: MeasurementDatasetReceipt


class CollectionCommitCommand(_FencedRunCommand):
    schema_version: Literal["scopecat.collection_commit_command.v1"] = (
        "scopecat.collection_commit_command.v1"
    )
    command_id: NonEmptyText
    chunk: CollectionChunk

    @model_validator(mode="after")
    def validate_chunk(self) -> CollectionCommitCommand:
        if self.chunk.run_id != self.run_id:
            raise ValueError("collection commit command run ids must match")
        if self.command_id != self.chunk.operation_id:
            raise ValueError("collection commit command id must match its operation")
        return self


class CollectionCommitReceipt(_WireModel):
    schema_version: Literal["scopecat.collection_commit_receipt.v1"] = (
        "scopecat.collection_commit_receipt.v1"
    )
    command_id: NonEmptyText
    receipt: CollectionChunkReceipt


class CollectionResolveCommand(_FencedRunCommand):
    schema_version: Literal["scopecat.collection_resolve_command.v1"] = (
        "scopecat.collection_resolve_command.v1"
    )
    receipt: CollectionChunkReceipt


class CollectionResolveReceipt(_WireModel):
    schema_version: Literal["scopecat.collection_resolve_receipt.v1"] = (
        "scopecat.collection_resolve_receipt.v1"
    )
    chunk: CollectionChunk


class PayloadCommitCommand(_FencedRunCommand):
    schema_version: Literal["scopecat.payload_commit_command.v1"] = (
        "scopecat.payload_commit_command.v1"
    )
    command_id: NonEmptyText
    evidence: PayloadEvidence

    @model_validator(mode="after")
    def validate_evidence(self) -> PayloadCommitCommand:
        if self.evidence.run_id != self.run_id:
            raise ValueError("payload commit command run ids must match")
        if self.command_id != self.evidence.operation_id:
            raise ValueError("payload commit command id must match its operation")
        return self


class PayloadCommitReceipt(_WireModel):
    schema_version: Literal["scopecat.payload_commit_receipt.v1"] = (
        "scopecat.payload_commit_receipt.v1"
    )
    command_id: NonEmptyText
    evidence: CommittedPayloadEvidence


class TerminalModelWrite(_WireModel):
    ref: NonEmptyText
    value: dict[str, JsonValue]


class TerminalRecordSetWrite(_WireModel):
    ref: NonEmptyText
    records: tuple[dict[str, JsonValue], ...]


class TerminalRunCommitCommand(_FencedRunCommand):
    """Lossless JSON projection of one interpreter terminal commit."""

    schema_version: Literal["scopecat.terminal_run_commit_command.v1"] = (
        "scopecat.terminal_run_commit_command.v1"
    )
    command_id: NonEmptyText
    manifest: RunManifest
    models: tuple[TerminalModelWrite, ...] = ()
    record_sets: tuple[TerminalRecordSetWrite, ...] = ()

    @model_validator(mode="after")
    def validate_manifest(self) -> TerminalRunCommitCommand:
        if self.manifest.run_id != self.run_id:
            raise ValueError("terminal commit and manifest run ids must match")
        if self.manifest.lifecycle != "terminal":
            raise ValueError("terminal commit requires a terminal manifest")
        if self.command_id != f"terminal:{self.run_id}":
            raise ValueError("terminal command id must match its run")
        return self


class TerminalRunCommitReceipt(_WireModel):
    schema_version: Literal["scopecat.terminal_run_commit_receipt.v1"] = (
        "scopecat.terminal_run_commit_receipt.v1"
    )
    command_id: NonEmptyText
    manifest: RunManifest


class AttentionResolutionCommand(_WireModel):
    """Explicit operator decision for a quarantined run."""

    schema_version: Literal["scopecat.attention_resolution_command.v1"] = (
        "scopecat.attention_resolution_command.v1"
    )
    run_id: NonEmptyText
    action: AttentionResolutionAction


class AttentionResolutionReceipt(_WireModel):
    schema_version: Literal["scopecat.attention_resolution_receipt.v1"] = (
        "scopecat.attention_resolution_receipt.v1"
    )
    run_id: NonEmptyText
    action: AttentionResolutionAction
    state: Literal["attention_required", "accepted", "terminal"]
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
    "AttentionResolutionAction",
    "AttentionResolutionCommand",
    "AttentionResolutionReceipt",
    "CandidateConfigActivationCommand",
    "CandidateConfigActivationReceipt",
    "CollectionCommitCommand",
    "CollectionCommitReceipt",
    "CollectionResolveCommand",
    "CollectionResolveReceipt",
    "ConfigActivationReceipt",
    "ConfigEntryActivationCommand",
    "ConfigImportReceipt",
    "ConfigRollbackCommand",
    "DelegatedPlanSummary",
    "DelegatedRunSubmission",
    "DirectConfigImportCommand",
    "ExecutionMode",
    "ExecutionRecoveryRequest",
    "ExecutionRecoverySnapshot",
    "ExecutionTransitionBatch",
    "ExecutionTransitionBatchReceipt",
    "ExecutorHeartbeat",
    "ExecutorLease",
    "ExecutorStartRequest",
    "ExperimentCatalog",
    "ManagedRunSubmission",
    "MeasurementAppendCommand",
    "MeasurementAppendReceipt",
    "MeasurementSealCommand",
    "MeasurementSealReceipt",
    "ParameterProposalReviewCommand",
    "ParameterProposalReviewReceipt",
    "PayloadCommitCommand",
    "PayloadCommitReceipt",
    "RegisteredExperimentDescriptor",
    "ResourceClaimDescriptor",
    "ResourceClaimKind",
    "RunAdmission",
    "RunAttachmentCommand",
    "RunAttachmentReceipt",
    "RunSubmission",
    "TerminalModelWrite",
    "TerminalRecordSetWrite",
    "TerminalRunCommitCommand",
    "TerminalRunCommitReceipt",
]

"""Domain-neutral durable contracts for multi-run procedures."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PlainSerializer,
    field_validator,
    model_validator,
)

from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.frozen import freeze_json_mapping, thaw_json_value
from scopecat.kernel.run_outcome import utc_now
from scopecat.records.analysis import AnalysisSubject
from scopecat.records.config import ConfigContentHash
from scopecat.records.content import Sha256ContentHash

type _NonEmptyText = Annotated[str, Field(min_length=1)]


def _freeze_procedure_intent(value: Mapping[str, object]) -> Mapping[str, object]:
    return freeze_json_mapping(value, path="intent")


def _serialize_procedure_intent(value: Mapping[str, object]) -> object:
    return thaw_json_value(value)


type ProcedureIntent = Annotated[
    Mapping[str, object],
    AfterValidator(_freeze_procedure_intent),
    PlainSerializer(
        _serialize_procedure_intent,
        return_type=dict[str, JsonValue],
    ),
]

type ProcedureRunState = Literal[
    "ready",
    "leased",
    "waiting",
    "attention_required",
    "closed",
]
type ProcedureStepOperation = Literal["run", "analysis", "config_activation"]
type ProcedureStepAttemptState = Literal[
    "running",
    "succeeded",
    "failed",
    "attention_required",
]
type ProcedureCloseStatus = Literal["succeeded", "failed", "cancelled"]


class _ProcedureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProcedureDefinitionRef(_ProcedureModel):
    """Versioned executable definition pinned by its implementation fingerprint."""

    id: _NonEmptyText
    version: _NonEmptyText
    fingerprint: Sha256ContentHash

    @field_validator("id", "version")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("procedure definition identity must be non-empty")
        return value


def procedure_intent_hash(
    definition: ProcedureDefinitionRef,
    intent: Mapping[str, object],
) -> Sha256ContentHash:
    """Hash the exact definition and canonical JSON intent used by a worker."""

    identity = {
        "definition": definition.model_dump(mode="json"),
        "intent": cast("dict[str, JsonValue]", thaw_json_value(intent)),
    }
    return f"sha256:{stable_content_hash(identity)}"


class RunTerminalWait(_ProcedureModel):
    """Wake the procedure after one exact child run becomes terminal."""

    kind: Literal["run_terminal"] = "run_terminal"
    run_id: _NonEmptyText


class AnalysisPublicationWait(_ProcedureModel):
    """Wake the procedure after one exact analysis publication exists."""

    kind: Literal["analysis_publication"] = "analysis_publication"
    subject: AnalysisSubject
    analysis_record_id: _NonEmptyText


type ProcedureWaitCondition = Annotated[
    RunTerminalWait | AnalysisPublicationWait,
    Field(discriminator="kind"),
]


class ProcedureClosure(_ProcedureModel):
    """Terminal result of a procedure run."""

    status: ProcedureCloseStatus
    closed_at: datetime = Field(default_factory=utc_now)
    reason: str | None = None

    @model_validator(mode="after")
    def validate_reason(self) -> ProcedureClosure:
        if self.status == "succeeded":
            if self.reason is not None:
                raise ValueError("successful procedure closure cannot have a reason")
        elif self.reason is None or not self.reason.strip():
            raise ValueError("failed or cancelled procedure closure requires a reason")
        return self


class RunOutputRef(_ProcedureModel):
    """Exact child run produced by a procedure step."""

    kind: Literal["run"] = "run"
    run_id: _NonEmptyText


class AnalysisPublicationOutputRef(_ProcedureModel):
    """Exact analysis publication produced by a procedure step."""

    kind: Literal["analysis"] = "analysis"
    subject: AnalysisSubject
    analysis_record_id: _NonEmptyText


class ConfigActivationOutputRef(_ProcedureModel):
    """Exact configuration-registry activation produced by a procedure step."""

    kind: Literal["config_activation"] = "config_activation"
    generation: int = Field(ge=1)
    entry_id: _NonEmptyText
    entry_content_hash: ConfigContentHash


type ProcedureStepOutputRef = Annotated[
    RunOutputRef | AnalysisPublicationOutputRef | ConfigActivationOutputRef,
    Field(discriminator="kind"),
]


class ProcedureRun(_ProcedureModel):
    """Current durable state of one version-pinned procedure invocation."""

    procedure_run_id: _NonEmptyText
    request_key: _NonEmptyText
    definition: ProcedureDefinitionRef
    intent: ProcedureIntent
    intent_hash: Sha256ContentHash
    revision: int = Field(ge=1)
    state: ProcedureRunState
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    wait_condition: ProcedureWaitCondition | None = None
    attention_reason: str | None = None
    closure: ProcedureClosure | None = None

    @model_validator(mode="after")
    def validate_state_details(self) -> ProcedureRun:
        expected_intent_hash = procedure_intent_hash(self.definition, self.intent)
        if self.intent_hash != expected_intent_hash:
            raise ValueError(
                "procedure intent hash must cover its definition and complete intent"
            )
        if self.updated_at < self.created_at:
            raise ValueError("procedure run cannot be updated before it is created")

        if self.state == "waiting":
            if self.wait_condition is None:
                raise ValueError("waiting procedure run requires a wait condition")
        elif self.wait_condition is not None:
            raise ValueError("wait condition is only valid for a waiting procedure run")

        if self.state == "attention_required":
            if self.attention_reason is None or not self.attention_reason.strip():
                raise ValueError("attention-required procedure run requires a reason")
        elif self.attention_reason is not None:
            raise ValueError(
                "attention reason is only valid for an attention-required procedure run"
            )

        if self.state == "closed":
            if self.closure is None:
                raise ValueError("closed procedure run requires a closure")
            if not self.created_at <= self.closure.closed_at <= self.updated_at:
                raise ValueError(
                    "procedure closure time must be within its run lifetime"
                )
        elif self.closure is not None:
            raise ValueError("closure is only valid for a closed procedure run")
        return self


class ProcedureStepAttempt(_ProcedureModel):
    """One revisioned attempt at a stable, intent-identified procedure step."""

    procedure_run_id: _NonEmptyText
    step_key: _NonEmptyText
    attempt: int = Field(ge=1)
    operation: ProcedureStepOperation
    intent_hash: Sha256ContentHash
    inputs: tuple[ProcedureStepOutputRef, ...] = ()
    revision: int = Field(ge=1)
    state: ProcedureStepAttemptState
    started_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    output: ProcedureStepOutputRef | None = None
    failure_reason: str | None = None
    attention_reason: str | None = None

    @field_validator("inputs")
    @classmethod
    def validate_unique_inputs(
        cls,
        value: tuple[ProcedureStepOutputRef, ...],
    ) -> tuple[ProcedureStepOutputRef, ...]:
        identities = tuple(item.model_dump_json() for item in value)
        if len(identities) != len(set(identities)):
            raise ValueError("procedure step input references must be unique")
        return value

    @model_validator(mode="after")
    def validate_state_details(self) -> ProcedureStepAttempt:
        if self.updated_at < self.started_at:
            raise ValueError("procedure step cannot be updated before it starts")
        if self.finished_at is not None and not (
            self.started_at <= self.finished_at <= self.updated_at
        ):
            raise ValueError("procedure step finish time must be within its lifetime")

        if self.state == "running":
            if self.finished_at is not None:
                raise ValueError("running procedure step cannot be finished")
        elif self.state == "succeeded":
            if self.finished_at is None or self.output is None:
                raise ValueError(
                    "successful procedure step requires output and finish time"
                )
        elif self.state == "failed":
            if self.finished_at is None:
                raise ValueError("failed procedure step requires a finish time")
            if self.failure_reason is None or not self.failure_reason.strip():
                raise ValueError("failed procedure step requires a reason")
        else:
            if self.attention_reason is None or not self.attention_reason.strip():
                raise ValueError("attention-required procedure step requires a reason")
            if self.finished_at is not None:
                raise ValueError("attention-required procedure step cannot be finished")

        if self.state != "succeeded" and self.output is not None:
            raise ValueError("output is only valid for a successful procedure step")
        if self.state != "failed" and self.failure_reason is not None:
            raise ValueError("failure reason is only valid for a failed procedure step")
        if self.state != "attention_required" and self.attention_reason is not None:
            raise ValueError(
                "attention reason is only valid for an attention-required "
                "procedure step"
            )
        if self.output is not None and self.output.kind != self.operation:
            raise ValueError("procedure step output kind must match its operation")
        return self

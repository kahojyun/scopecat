"""Structured execution evidence models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.problems import Problem
from scopecat.records.instrument import (
    InstrumentStateSetting,
    InstrumentStateSnapshot,
    StateMemberIdentity,
    state_member_identity,
)
from scopecat.records.metadata import JsonMetadata


def _exclude_empty(value: object) -> bool:
    return not value


def _exclude_none(value: object) -> bool:
    return value is None


class DomainExecutionId(BaseModel):
    """Deterministic identity for one domain job execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    logical_compute_node_id: str
    invocation_id: str
    intent_fingerprint: str

    @field_validator(
        "run_id",
        "logical_compute_node_id",
        "invocation_id",
        "intent_fingerprint",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            raise ValueError("domain execution identity fields must be non-empty")
        return value

    @property
    def execution_key(self) -> str:
        return stable_content_hash(
            {
                "schema": "scopecat.domain_execution_key.v1",
                "run_id": self.run_id,
                "logical_compute_node_id": self.logical_compute_node_id,
                "invocation_id": self.invocation_id,
                "intent_fingerprint": self.intent_fingerprint,
            }
        )

    @property
    def operation_id(self) -> str:
        return f"domain:{self.execution_key}:execute"


class DomainInvocationIntent(BaseModel):
    """Durable, payload-free identity of one executable domain invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: str
    target_id: str
    compiler_id: str
    capability_fingerprint: str
    artifact_id: str
    artifact_fingerprint: str
    result_contract_fingerprint: str
    target_intent: dict[str, JsonValue]
    execution_summary: dict[str, JsonValue]
    intent_fingerprint: str

    @classmethod
    def create(
        cls,
        *,
        invocation_id: str,
        target_id: str,
        compiler_id: str,
        capability_fingerprint: str,
        artifact_id: str,
        artifact_fingerprint: str,
        result_contract_fingerprint: str,
        target_intent: Mapping[str, JsonValue],
        execution_summary: Mapping[str, JsonValue],
    ) -> Self:
        selected_target_intent = dict(target_intent)
        selected_execution_summary = dict(execution_summary)
        return cls(
            invocation_id=invocation_id,
            target_id=target_id,
            compiler_id=compiler_id,
            capability_fingerprint=capability_fingerprint,
            artifact_id=artifact_id,
            artifact_fingerprint=artifact_fingerprint,
            result_contract_fingerprint=result_contract_fingerprint,
            target_intent=selected_target_intent,
            execution_summary=selected_execution_summary,
            intent_fingerprint=_domain_invocation_intent_fingerprint(
                invocation_id=invocation_id,
                target_id=target_id,
                compiler_id=compiler_id,
                capability_fingerprint=capability_fingerprint,
                artifact_id=artifact_id,
                artifact_fingerprint=artifact_fingerprint,
                result_contract_fingerprint=result_contract_fingerprint,
                target_intent=selected_target_intent,
                execution_summary=selected_execution_summary,
            ),
        )

    @field_validator(
        "invocation_id",
        "target_id",
        "compiler_id",
        "capability_fingerprint",
        "artifact_id",
        "artifact_fingerprint",
        "result_contract_fingerprint",
        "intent_fingerprint",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            raise ValueError("domain invocation identity fields must be non-empty")
        return value

    @model_validator(mode="after")
    def validate_intent_fingerprint(self) -> DomainInvocationIntent:
        expected = _domain_invocation_intent_fingerprint(
            invocation_id=self.invocation_id,
            target_id=self.target_id,
            compiler_id=self.compiler_id,
            capability_fingerprint=self.capability_fingerprint,
            artifact_id=self.artifact_id,
            artifact_fingerprint=self.artifact_fingerprint,
            result_contract_fingerprint=self.result_contract_fingerprint,
            target_intent=self.target_intent,
            execution_summary=self.execution_summary,
        )
        if self.intent_fingerprint != expected:
            raise ValueError(
                "domain invocation fingerprint does not cover its complete intent"
            )
        return self


class DomainJobCheckpoint(BaseModel):
    """Serializable pending state for one submitted target job.

    ``resume_token`` contains the target-owned JSON state needed to advance the
    same job after this boundary. ``progress`` is inspectable evidence only and
    must not be required for resumption. Revisions are strictly monotonic within
    one job and let execution reject stale or replayed transitions.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_key: str
    job_id: str
    revision: int = Field(ge=1)
    resume_token: dict[str, JsonValue]
    progress: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("execution_key", "job_id")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        if not value:
            raise ValueError("domain job checkpoint identities must be non-empty")
        return value


class DomainExecutionReceipt(BaseModel):
    """Provider outcome evidence for one terminal target job.

    ``completed`` supplies correlated result evidence and proves that the
    realtime call completed. ``not_executed`` proves that realtime execution
    did not begin, even if declared setup work changed state. ``unknown`` means
    hardware may have changed without a correlated completion. Both negative
    statuses carry problems and no result evidence. ``execution_evidence`` is
    target-owned structured context reported with the call outcome. It is not
    host instrument readback and does not imply that the described state can
    be restored.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_key: str
    status: Literal["completed", "not_executed", "unknown"]
    result_fingerprint: str | None = None
    result_count: int | None = Field(default=None, ge=0)
    execution_evidence: dict[str, JsonValue] = Field(default_factory=dict)
    problems: tuple[Problem, ...] = ()

    @field_validator("execution_key")
    @classmethod
    def validate_execution_key(cls, value: str) -> str:
        if not value:
            raise ValueError("domain execution receipts require an execution key")
        return value

    @model_validator(mode="after")
    def validate_outcome(self) -> DomainExecutionReceipt:
        has_result = (
            self.result_fingerprint is not None and self.result_count is not None
        )
        if self.status == "completed":
            if not has_result or not self.result_fingerprint or self.problems:
                raise ValueError(
                    "completed domain receipts require result evidence and no problems"
                )
        elif (
            has_result
            or self.result_fingerprint is not None
            or self.result_count is not None
            or not self.problems
        ):
            raise ValueError(
                "negative domain receipts require problems and no result evidence"
            )
        return self


class DomainJobCheckpointTransition(BaseModel):
    """One pending job boundary that is durable before the next resume."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["checkpoint"] = "checkpoint"
    checkpoint: DomainJobCheckpoint

    @property
    def execution_key(self) -> str:
        return self.checkpoint.execution_key


class DomainJobInvocationTransition(BaseModel):
    """One complete observed intent, persisted before start or in a batch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["invocation"] = "invocation"
    execution_id: DomainExecutionId
    intent: DomainInvocationIntent

    @model_validator(mode="after")
    def validate_intent(self) -> DomainJobInvocationTransition:
        if (
            self.execution_id.invocation_id != self.intent.invocation_id
            or self.execution_id.intent_fingerprint != self.intent.intent_fingerprint
        ):
            raise ValueError("domain execution identity does not match its intent")
        return self

    @property
    def execution_key(self) -> str:
        return self.execution_id.execution_key


class DomainJobTerminalTransition(BaseModel):
    """One terminal provider outcome observed before result realization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["terminal"] = "terminal"
    receipt: DomainExecutionReceipt

    @property
    def execution_key(self) -> str:
        return self.receipt.execution_key


type DomainJobTransitionRecord = Annotated[
    DomainJobInvocationTransition
    | DomainJobCheckpointTransition
    | DomainJobTerminalTransition,
    Field(discriminator="kind"),
]


class InstrumentStateEvidenceSummary(BaseModel):
    """Compact, neutral index of state transitions kept outside datasets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_ids: tuple[str, ...]
    baseline_change_count: int = Field(ge=0)
    final_change_count: int = Field(ge=0)
    baseline_changed_instrument_ids: tuple[str, ...]
    final_changed_instrument_ids: tuple[str, ...]
    missing_final_instrument_ids: tuple[str, ...]
    finalization_action_count: int = Field(
        default=0,
        ge=0,
        exclude_if=_exclude_empty,
    )
    rejected_finalization_action_count: int = Field(
        default=0,
        ge=0,
        exclude_if=_exclude_empty,
    )
    state_action_count: int = Field(default=0, ge=0, exclude_if=_exclude_empty)
    retained_state_action_count: int = Field(
        default=0,
        ge=0,
        exclude_if=_exclude_empty,
    )
    state_action_detail_complete: bool | None = Field(
        default=None,
        exclude_if=_exclude_none,
    )


class InstrumentStateActionEvidence(BaseModel):
    """One confirmed state action executed while a run was active.

    ``assignments`` contains only members actually sent to the driver. Driver
    metadata is command evidence and must not be interpreted as analog readback.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    point_index: int | None = Field(default=None, ge=0)
    status: Literal["applied", "unchanged"]
    assignments: tuple[InstrumentStateSetting, ...] = ()
    metadata: JsonMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_outcome(self) -> InstrumentStateActionEvidence:
        identities = [
            state_member_identity(assignment.target) for assignment in self.assignments
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("state action assignment targets must be unique")
        if self.status == "applied" and not self.assignments:
            raise ValueError("an applied state action requires assignments")
        if self.status == "unchanged" and self.assignments:
            raise ValueError("an unchanged state action cannot contain assignments")
        return self


class InstrumentStateActionEvidenceLog(BaseModel):
    """A bounded ordered prefix of state actions and its complete total."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_count: int = Field(ge=1)
    retained_prefix: tuple[InstrumentStateActionEvidence, ...]
    detail_complete: bool

    @model_validator(mode="after")
    def validate_retention(self) -> InstrumentStateActionEvidenceLog:
        retained_count = len(self.retained_prefix)
        if retained_count > self.total_count:
            raise ValueError("retained state actions cannot exceed the total count")
        if self.detail_complete != (retained_count == self.total_count):
            raise ValueError(
                "state action detail completeness must match the retained count"
            )
        return self


class InstrumentFinalizationActionEvidence(BaseModel):
    """One durable, payload-free action attempted during device finalization."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    kind: Literal["abort", "restore_baseline", "safe_operation", "safe_state"]
    status: Literal["completed", "unchanged", "rejected"]
    metadata: JsonMetadata = Field(default_factory=dict)
    problems: tuple[Problem, ...] = ()

    @model_validator(mode="after")
    def validate_outcome(self) -> InstrumentFinalizationActionEvidence:
        if self.status == "rejected" and not self.problems:
            raise ValueError("a rejected finalization action requires a problem")
        if self.status != "rejected" and self.problems:
            raise ValueError("a completed finalization action cannot contain problems")
        return self


class InstrumentStateEvidence(BaseModel):
    """Durable state evidence across provisioning and execution.

    ``observed_state`` is the fresh read after ownership is acquired.
    ``baseline_state`` is the execution baseline after the run policy.
    ``final_state`` is best-effort terminal readback gathered during hardware
    release. It may be incomplete and does not imply a successful run.
    ``state_actions`` retains a bounded prefix of confirmed in-run state
    commands without treating driver command metadata as physical readback.
    ``finalization_actions`` retains the ordered command evidence returned by
    that release without treating command confirmation as physical readback.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    observed_state: list[InstrumentStateSnapshot] = Field(default_factory=list)
    baseline_state: list[InstrumentStateSnapshot] = Field(default_factory=list)
    final_state: list[InstrumentStateSnapshot] = Field(default_factory=list)
    state_actions: InstrumentStateActionEvidenceLog | None = Field(
        default=None,
        exclude_if=_exclude_none,
    )
    finalization_actions: list[InstrumentFinalizationActionEvidence] = Field(
        default_factory=list,
        exclude_if=_exclude_empty,
    )

    @model_validator(mode="after")
    def validate_baseline_evidence(self) -> InstrumentStateEvidence:
        observed_ids = [state.instrument_id for state in self.observed_state]
        baseline_ids = [state.instrument_id for state in self.baseline_state]
        if observed_ids != baseline_ids:
            raise ValueError(
                "observed and baseline state must identify instruments "
                "in the same order"
            )
        if len(observed_ids) != len(set(observed_ids)):
            raise ValueError("instrument baseline evidence ids must be unique")
        final_ids = [state.instrument_id for state in self.final_state]
        if len(final_ids) != len(set(final_ids)):
            raise ValueError("instrument final evidence ids must be unique")
        unknown_final_ids = sorted(set(final_ids) - set(observed_ids))
        if unknown_final_ids:
            raise ValueError(
                "final state references instruments absent from baseline evidence: "
                + ", ".join(unknown_final_ids)
            )
        return self


def summarize_instrument_state_evidence(
    evidence: InstrumentStateEvidence,
) -> InstrumentStateEvidenceSummary:
    """Summarize property changes without treating intentional changes as faults."""

    observed = {state.instrument_id: state for state in evidence.observed_state}
    baseline = {state.instrument_id: state for state in evidence.baseline_state}
    final = {state.instrument_id: state for state in evidence.final_state}
    baseline_changes = {
        instrument_id: _changed_property_count(
            observed[instrument_id],
            baseline[instrument_id],
        )
        for instrument_id in observed
    }
    final_changes = {
        instrument_id: _changed_property_count(
            baseline[instrument_id],
            final[instrument_id],
        )
        for instrument_id in final
    }
    instrument_ids = tuple(observed)
    return InstrumentStateEvidenceSummary(
        instrument_ids=instrument_ids,
        baseline_change_count=sum(baseline_changes.values()),
        final_change_count=sum(final_changes.values()),
        baseline_changed_instrument_ids=tuple(
            instrument_id
            for instrument_id in instrument_ids
            if baseline_changes[instrument_id]
        ),
        final_changed_instrument_ids=tuple(
            instrument_id
            for instrument_id in instrument_ids
            if final_changes.get(instrument_id, 0)
        ),
        missing_final_instrument_ids=tuple(
            instrument_id
            for instrument_id in instrument_ids
            if instrument_id not in final
        ),
        finalization_action_count=len(evidence.finalization_actions),
        rejected_finalization_action_count=sum(
            action.status == "rejected" for action in evidence.finalization_actions
        ),
        state_action_count=(
            0 if evidence.state_actions is None else evidence.state_actions.total_count
        ),
        retained_state_action_count=(
            0
            if evidence.state_actions is None
            else len(evidence.state_actions.retained_prefix)
        ),
        state_action_detail_complete=(
            None
            if evidence.state_actions is None
            else evidence.state_actions.detail_complete
        ),
    )


def _changed_property_count(
    before: InstrumentStateSnapshot,
    after: InstrumentStateSnapshot,
) -> int:
    before_values = _state_property_values(before)
    after_values = _state_property_values(after)
    return sum(
        before_values.get(identity) != after_values.get(identity)
        for identity in before_values.keys() | after_values.keys()
    )


def _state_property_values(
    state: InstrumentStateSnapshot,
) -> dict[StateMemberIdentity, object]:
    return {
        state_member_identity(item.target): item.value for item in state.observations
    }


def _domain_invocation_intent_fingerprint(
    *,
    invocation_id: str,
    target_id: str,
    compiler_id: str,
    capability_fingerprint: str,
    artifact_id: str,
    artifact_fingerprint: str,
    result_contract_fingerprint: str,
    target_intent: Mapping[str, JsonValue],
    execution_summary: Mapping[str, JsonValue],
) -> str:
    return stable_content_hash(
        {
            "schema": "scopecat.sdk.domain.invocation_intent_identity.v3",
            "invocation_id": invocation_id,
            "target_id": target_id,
            "compiler_id": compiler_id,
            "capability_fingerprint": capability_fingerprint,
            "artifact_id": artifact_id,
            "artifact_fingerprint": artifact_fingerprint,
            "result_contract_fingerprint": result_contract_fingerprint,
            "target_intent": target_intent,
            "execution_summary": execution_summary,
        }
    )

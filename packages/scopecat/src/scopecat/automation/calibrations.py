"""Immutable calibration-cohort planning and evidence contracts.

Calibration dependencies deliberately point only at exact prior successes.  A
cohort is therefore a bounded atomic admission batch, not a general-purpose
workflow graph: members of the same cohort cannot depend on one another.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from scopecat.automation.models import (
    ProcedureClosure,
    ProcedureDefinitionRef,
    ProcedureIntent,
    ProcedureRunState,
)
from scopecat.kernel.content_identity import stable_content_hash
from scopecat.records.config import ConfigContentHash
from scopecat.records.content import Sha256ContentHash
from scopecat.records.run import ConfigRegistryRunConfigSource

type _NonEmptyText = Annotated[str, Field(min_length=1)]

MAX_CALIBRATION_COHORT_MEMBERS = 200
MAX_CALIBRATION_STATUS_KEYS = 200

_CALIBRATION_KEY_CODEC = "scopecat.calibration-key.v1"
_CALIBRATION_FRESHNESS_CODEC = "scopecat.calibration-freshness.v2"
_CALIBRATION_COHORT_SPEC_CODEC = "scopecat.calibration-cohort-spec.v1"
_CALIBRATION_COHORT_MEMBER_REQUEST_CODEC = (
    "scopecat.calibration-cohort-member-request.v1"
)


class _CalibrationModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class CalibrationDefinitionRef(_CalibrationModel):
    """Version-pinned calibration meaning, independent of its procedure."""

    id: _NonEmptyText
    version: _NonEmptyText
    fingerprint: Sha256ContentHash

    @field_validator("id", "version")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration definition identity")


class CalibrationTargetRef(_CalibrationModel):
    """Stable logical target addressed by one calibration definition."""

    kind: _NonEmptyText
    id: _NonEmptyText

    @field_validator("kind", "id")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration target identity")


class CalibrationConfigSourceRef(_CalibrationModel):
    """Exact active configuration basis frozen into a cohort decision."""

    kind: Literal["config_registry"] = "config_registry"
    selector: Literal["active"] = "active"
    entry_id: _NonEmptyText
    config_ref: _NonEmptyText
    content_hash: ConfigContentHash
    registry_generation: int = Field(ge=1)

    @field_validator("entry_id", "config_ref")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration config source identity")

    @classmethod
    def from_run_config_source(
        cls,
        source: ConfigRegistryRunConfigSource,
    ) -> CalibrationConfigSourceRef:
        if source.registry_generation is None:
            raise ValueError("calibration config source requires registry generation")
        if source.selector != "active":
            raise ValueError("calibration config source must select active config")
        return cls(
            entry_id=source.entry_id,
            config_ref=source.config_ref,
            content_hash=source.content_hash,
            registry_generation=source.registry_generation,
        )


def calibration_key(
    definition_id: str,
    target: CalibrationTargetRef,
) -> str:
    """Identify one logical calibration across definition/procedure revisions."""

    selected_definition_id = _non_blank(
        definition_id,
        field_name="calibration definition id",
    )
    digest = stable_content_hash(
        {
            "codec": _CALIBRATION_KEY_CODEC,
            "definition_id": selected_definition_id,
            "target": target.model_dump(mode="json"),
        }
    )
    return f"calibration:{digest}"


class CalibrationDependencyEvidence(_CalibrationModel):
    """Flat identity of one exact successful dependency attempt.

    Keeping this projection flat prevents a success from recursively embedding
    the complete dependency history of every earlier calibration.
    """

    calibration_key: _NonEmptyText
    cohort_id: _NonEmptyText
    member_id: _NonEmptyText
    procedure_run_id: _NonEmptyText
    succeeded_at: datetime

    @field_validator(
        "calibration_key",
        "cohort_id",
        "member_id",
        "procedure_run_id",
    )
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration dependency identity")

    @field_validator("succeeded_at")
    @classmethod
    def canonicalize_succeeded_at(cls, value: datetime) -> datetime:
        return _canonical_utc(value, field_name="succeeded_at")

    @classmethod
    def from_success(
        cls,
        success: CalibrationSuccessRef,
    ) -> CalibrationDependencyEvidence:
        return cls(
            calibration_key=success.attempt.calibration_key,
            cohort_id=success.attempt.cohort_id,
            member_id=success.attempt.member_id,
            procedure_run_id=success.attempt.procedure_run_id,
            succeeded_at=success.succeeded_at,
        )


class CalibrationAttemptRef(_CalibrationModel):
    """Exact durable ProcedureRun admitted for one calibration member."""

    calibration_key: _NonEmptyText
    cohort_id: _NonEmptyText
    member_id: _NonEmptyText
    procedure_run_id: _NonEmptyText
    definition: CalibrationDefinitionRef
    target: CalibrationTargetRef
    procedure: ProcedureDefinitionRef
    input_fingerprint: Sha256ContentHash
    dependencies: tuple[CalibrationDependencyEvidence, ...] = Field(
        default=(),
        max_length=MAX_CALIBRATION_STATUS_KEYS,
    )
    freshness_fingerprint: Sha256ContentHash
    admitted_at: datetime

    @field_validator(
        "calibration_key",
        "cohort_id",
        "member_id",
        "procedure_run_id",
    )
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration attempt identity")

    @field_validator("admitted_at")
    @classmethod
    def canonicalize_admitted_at(cls, value: datetime) -> datetime:
        return _canonical_utc(value, field_name="admitted_at")

    @field_validator("dependencies")
    @classmethod
    def canonicalize_dependencies(
        cls,
        value: tuple[CalibrationDependencyEvidence, ...],
    ) -> tuple[CalibrationDependencyEvidence, ...]:
        return _canonical_dependencies(
            value,
            label="calibration attempt dependency key",
        )

    @model_validator(mode="after")
    def validate_calibration_key(self) -> CalibrationAttemptRef:
        expected = calibration_key(self.definition.id, self.target)
        if self.calibration_key != expected:
            raise ValueError(
                "calibration attempt key must identify its definition and target"
            )
        if any(
            dependency.calibration_key == self.calibration_key
            for dependency in self.dependencies
        ):
            raise ValueError("calibration attempt cannot depend on itself")
        expected_freshness = calibration_freshness_fingerprint(
            definition=self.definition,
            target=self.target,
            procedure=self.procedure,
            input_fingerprint=self.input_fingerprint,
            dependencies=self.dependencies,
        )
        if self.freshness_fingerprint != expected_freshness:
            raise ValueError(
                "calibration attempt freshness must cover its exact inputs"
            )
        return self


class CalibrationSuccessRef(_CalibrationModel):
    """Exact successful attempt admitted before a dependent cohort."""

    attempt: CalibrationAttemptRef
    succeeded_at: datetime

    @field_validator("succeeded_at")
    @classmethod
    def canonicalize_succeeded_at(cls, value: datetime) -> datetime:
        return _canonical_utc(value, field_name="succeeded_at")

    @model_validator(mode="after")
    def validate_success_time(self) -> CalibrationSuccessRef:
        if self.succeeded_at < self.attempt.admitted_at:
            raise ValueError("calibration success cannot precede attempt admission")
        return self

    @property
    def dependency_evidence(self) -> CalibrationDependencyEvidence:
        return CalibrationDependencyEvidence.from_success(self)


class CalibrationAttemptStatus(_CalibrationModel):
    """Observed ProcedureRun state for one exact calibration attempt."""

    attempt: CalibrationAttemptRef
    procedure_state: ProcedureRunState
    procedure_revision: int = Field(ge=1)
    updated_at: datetime
    closure: ProcedureClosure | None = None

    @field_validator("updated_at")
    @classmethod
    def canonicalize_updated_at(cls, value: datetime) -> datetime:
        return _canonical_utc(value, field_name="updated_at")

    @field_validator("closure")
    @classmethod
    def canonicalize_closure(
        cls,
        value: ProcedureClosure | None,
    ) -> ProcedureClosure | None:
        if value is None:
            return None
        return value.model_copy(
            update={
                "closed_at": _canonical_utc(
                    value.closed_at,
                    field_name="closure.closed_at",
                )
            }
        )

    @model_validator(mode="after")
    def validate_run_state(self) -> CalibrationAttemptStatus:
        if self.updated_at < self.attempt.admitted_at:
            raise ValueError("calibration attempt update cannot precede admission")
        if self.procedure_state == "closed":
            if self.closure is None:
                raise ValueError("closed calibration attempt requires a closure")
            if self.closure.closed_at > self.updated_at:
                raise ValueError("calibration closure cannot follow its update time")
        elif self.closure is not None:
            raise ValueError("only a closed calibration attempt can have a closure")
        return self


class CalibrationStatus(_CalibrationModel):
    """Latest attempt and latest success for one logical calibration key."""

    calibration_key: _NonEmptyText
    latest_attempt: CalibrationAttemptStatus | None = None
    latest_success: CalibrationSuccessRef | None = None

    @field_validator("calibration_key")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration status key")

    @model_validator(mode="after")
    def validate_evidence(self) -> CalibrationStatus:
        if self.latest_attempt is None and self.latest_success is not None:
            raise ValueError("calibration success requires a latest attempt")
        if (
            self.latest_attempt is not None
            and self.latest_attempt.attempt.calibration_key != self.calibration_key
        ):
            raise ValueError("latest calibration attempt must match the status key")
        if (
            self.latest_success is not None
            and self.latest_success.attempt.calibration_key != self.calibration_key
        ):
            raise ValueError("latest calibration success must match the status key")

        attempt_status = self.latest_attempt
        latest_success = self.latest_success
        if attempt_status is None or latest_success is None:
            if (
                attempt_status is not None
                and attempt_status.procedure_state == "closed"
                and attempt_status.closure is not None
                and attempt_status.closure.status == "succeeded"
            ):
                raise ValueError(
                    "successful latest attempt requires matching success evidence"
                )
            return self

        expected = _success_from_attempt_status(attempt_status)
        if expected is not None and expected != latest_success:
            raise ValueError("successful latest attempt must be the latest success")
        if (
            attempt_status.attempt.procedure_run_id
            == latest_success.attempt.procedure_run_id
            and expected != latest_success
        ):
            raise ValueError("latest success must exactly match its successful attempt")
        return self


class CalibrationStatusSnapshot(_CalibrationModel):
    """One server-clock observation used for cohort admission CAS."""

    observed_at: datetime
    fanout_scope: _NonEmptyText
    fanout_active_count: int = Field(ge=0)
    statuses: tuple[CalibrationStatus, ...] = Field(
        default=(),
        max_length=MAX_CALIBRATION_STATUS_KEYS,
    )

    @field_validator("observed_at")
    @classmethod
    def canonicalize_observed_at(cls, value: datetime) -> datetime:
        return _canonical_utc(value, field_name="observed_at")

    @field_validator("fanout_scope")
    @classmethod
    def validate_fanout_scope(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration fanout scope")

    @field_validator("statuses")
    @classmethod
    def validate_unique_statuses(
        cls,
        value: tuple[CalibrationStatus, ...],
    ) -> tuple[CalibrationStatus, ...]:
        _require_unique(
            (status.calibration_key for status in value),
            label="calibration status key",
        )
        return value

    @model_validator(mode="after")
    def validate_as_of_time(self) -> CalibrationStatusSnapshot:
        for status in self.statuses:
            success = status.latest_success
            if success is not None and success.succeeded_at > self.observed_at:
                raise ValueError(
                    "calibration success cannot follow its status observation"
                )
            attempt = status.latest_attempt
            if attempt is not None and attempt.updated_at > self.observed_at:
                raise ValueError(
                    "calibration attempt update cannot follow its status observation"
                )
        return self


class CalibrationMissingSuccessDueReason(_CalibrationModel):
    kind: Literal["missing_success"] = "missing_success"


class CalibrationExpiredDueReason(_CalibrationModel):
    kind: Literal["expired"] = "expired"
    previous_success: CalibrationSuccessRef
    expired_at: datetime

    @field_validator("expired_at")
    @classmethod
    def canonicalize_expired_at(cls, value: datetime) -> datetime:
        return _canonical_utc(value, field_name="expired_at")

    @model_validator(mode="after")
    def validate_expiry(self) -> CalibrationExpiredDueReason:
        if self.expired_at < self.previous_success.succeeded_at:
            raise ValueError("calibration expiry cannot precede its success")
        return self


class CalibrationDefinitionChangedDueReason(_CalibrationModel):
    kind: Literal["definition_changed"] = "definition_changed"
    previous_success: CalibrationSuccessRef


class CalibrationInputsChangedDueReason(_CalibrationModel):
    kind: Literal["inputs_changed"] = "inputs_changed"
    previous_success: CalibrationSuccessRef


class CalibrationDependencyChangedDueReason(_CalibrationModel):
    kind: Literal["dependency_changed"] = "dependency_changed"
    dependency_key: _NonEmptyText
    previous_success: CalibrationDependencyEvidence | None = None
    current_success: CalibrationDependencyEvidence | None = None

    @field_validator("dependency_key")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _non_blank(value, field_name="changed calibration dependency key")

    @model_validator(mode="after")
    def validate_evidence(self) -> CalibrationDependencyChangedDueReason:
        if self.previous_success is None and self.current_success is None:
            raise ValueError("changed dependency requires previous or current success")
        if (
            self.current_success is not None
            and self.current_success.calibration_key != self.dependency_key
        ):
            raise ValueError("current dependency success must match its key")
        if (
            self.previous_success is not None
            and self.previous_success.calibration_key != self.dependency_key
        ):
            raise ValueError("previous dependency success must match its key")
        if self.previous_success == self.current_success:
            raise ValueError("changed dependency successes must differ")
        return self


class CalibrationForcedDueReason(_CalibrationModel):
    kind: Literal["forced"] = "forced"
    reason: _NonEmptyText

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _non_blank(value, field_name="forced calibration reason")


type CalibrationDueReason = Annotated[
    CalibrationMissingSuccessDueReason
    | CalibrationExpiredDueReason
    | CalibrationDefinitionChangedDueReason
    | CalibrationInputsChangedDueReason
    | CalibrationDependencyChangedDueReason
    | CalibrationForcedDueReason,
    Field(discriminator="kind"),
]


def calibration_freshness_fingerprint(
    *,
    definition: CalibrationDefinitionRef,
    target: CalibrationTargetRef,
    procedure: ProcedureDefinitionRef,
    input_fingerprint: Sha256ContentHash,
    dependencies: tuple[CalibrationDependencyEvidence, ...],
) -> Sha256ContentHash:
    """Hash every exact input that determines calibration freshness.

    Dependency evidence is a set keyed by ``calibration_key``; authoring order
    therefore cannot change freshness identity.
    """

    canonical_dependencies = _canonical_dependencies(
        dependencies,
        label="calibration freshness dependency key",
    )

    digest = stable_content_hash(
        {
            "codec": _CALIBRATION_FRESHNESS_CODEC,
            "definition": definition.model_dump(mode="json"),
            "target": target.model_dump(mode="json"),
            "procedure": procedure.model_dump(mode="json"),
            "input_fingerprint": input_fingerprint,
            "dependencies": [
                dependency.model_dump(mode="json")
                for dependency in canonical_dependencies
            ],
        }
    )
    return f"sha256:{digest}"


class CalibrationCohortMemberSpec(_CalibrationModel):
    """Immutable project-side decision to admit one calibration procedure."""

    member_id: _NonEmptyText
    calibration_key: _NonEmptyText
    definition: CalibrationDefinitionRef
    target: CalibrationTargetRef
    procedure: ProcedureDefinitionRef
    intent: ProcedureIntent
    input_fingerprint: Sha256ContentHash
    dependencies: tuple[CalibrationDependencyEvidence, ...] = Field(
        default=(),
        max_length=MAX_CALIBRATION_STATUS_KEYS,
    )
    freshness_fingerprint: Sha256ContentHash
    due_reasons: tuple[CalibrationDueReason, ...] = Field(
        min_length=1,
        max_length=MAX_CALIBRATION_STATUS_KEYS,
    )

    @field_validator("member_id", "calibration_key")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration cohort member identity")

    @field_validator("dependencies")
    @classmethod
    def validate_unique_dependencies(
        cls,
        value: tuple[CalibrationDependencyEvidence, ...],
    ) -> tuple[CalibrationDependencyEvidence, ...]:
        return _canonical_dependencies(
            value,
            label="calibration dependency key",
        )

    @field_validator("due_reasons")
    @classmethod
    def validate_unique_due_reasons(
        cls,
        value: tuple[CalibrationDueReason, ...],
    ) -> tuple[CalibrationDueReason, ...]:
        _require_unique(
            (reason.model_dump_json() for reason in value),
            label="calibration due reason",
        )
        return value

    @model_validator(mode="after")
    def validate_member(self) -> CalibrationCohortMemberSpec:
        expected_key = calibration_key(self.definition.id, self.target)
        if self.calibration_key != expected_key:
            raise ValueError(
                "calibration member key must identify its definition and target"
            )
        if any(
            dependency.calibration_key == self.calibration_key
            for dependency in self.dependencies
        ):
            raise ValueError("calibration member cannot depend on itself")

        expected_freshness = calibration_freshness_fingerprint(
            definition=self.definition,
            target=self.target,
            procedure=self.procedure,
            input_fingerprint=self.input_fingerprint,
            dependencies=self.dependencies,
        )
        if self.freshness_fingerprint != expected_freshness:
            raise ValueError(
                "calibration freshness fingerprint must cover exact member inputs"
            )

        dependencies_by_key = {
            dependency.calibration_key: dependency for dependency in self.dependencies
        }
        for reason in self.due_reasons:
            if isinstance(reason, CalibrationExpiredDueReason):
                if (
                    reason.previous_success.attempt.calibration_key
                    != self.calibration_key
                ):
                    raise ValueError(
                        "member due reason success must match its calibration key"
                    )
            elif isinstance(
                reason,
                CalibrationDefinitionChangedDueReason
                | CalibrationInputsChangedDueReason,
            ):
                previous = reason.previous_success.attempt
                if previous.calibration_key != self.calibration_key:
                    raise ValueError(
                        "member due reason success must match its calibration key"
                    )
            elif isinstance(reason, CalibrationDependencyChangedDueReason):
                dependency = dependencies_by_key.get(reason.dependency_key)
                if reason.current_success != dependency:
                    raise ValueError(
                        "changed due reason must match current dependency evidence"
                    )
        return self


def calibration_cohort_member_request_key(
    cohort_id: str,
    spec: CalibrationCohortMemberSpec,
) -> str:
    """Derive the ProcedureRun request key for one exact cohort member."""

    selected_cohort_id = _non_blank(cohort_id, field_name="calibration cohort id")
    digest = stable_content_hash(
        {
            "codec": _CALIBRATION_COHORT_MEMBER_REQUEST_CODEC,
            "cohort_id": selected_cohort_id,
            "member": spec.model_dump(mode="json"),
        }
    )
    return f"calibration-cohort-member:{digest}"


class CalibrationCohortMember(_CalibrationModel):
    """Durable association between one cohort member and its ProcedureRun."""

    cohort_id: _NonEmptyText
    index: int = Field(ge=0)
    spec: CalibrationCohortMemberSpec
    procedure_run_id: _NonEmptyText
    request_key: _NonEmptyText
    admitted_at: datetime

    @field_validator("cohort_id", "procedure_run_id", "request_key")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration cohort member identity")

    @field_validator("admitted_at")
    @classmethod
    def canonicalize_admitted_at(cls, value: datetime) -> datetime:
        return _canonical_utc(value, field_name="admitted_at")

    @model_validator(mode="after")
    def validate_request_key(self) -> CalibrationCohortMember:
        expected = calibration_cohort_member_request_key(self.cohort_id, self.spec)
        if self.request_key != expected:
            raise ValueError(
                "cohort member request key must identify its exact immutable spec"
            )
        return self

    @property
    def attempt_ref(self) -> CalibrationAttemptRef:
        return CalibrationAttemptRef(
            calibration_key=self.spec.calibration_key,
            cohort_id=self.cohort_id,
            member_id=self.spec.member_id,
            procedure_run_id=self.procedure_run_id,
            definition=self.spec.definition,
            target=self.spec.target,
            procedure=self.spec.procedure,
            input_fingerprint=self.spec.input_fingerprint,
            dependencies=self.spec.dependencies,
            freshness_fingerprint=self.spec.freshness_fingerprint,
            admitted_at=self.admitted_at,
        )


class CalibrationCohortSpec(_CalibrationModel):
    """Complete immutable basis for one bounded cohort admission."""

    planner: CalibrationDefinitionRef
    config_source: CalibrationConfigSourceRef
    fanout_scope: _NonEmptyText
    max_in_flight: int = Field(ge=1, le=MAX_CALIBRATION_COHORT_MEMBERS)
    observed_fanout_active_count: int = Field(ge=0)
    evaluated_at: datetime
    observations: tuple[CalibrationStatus, ...] = Field(
        max_length=MAX_CALIBRATION_STATUS_KEYS,
    )
    members: tuple[CalibrationCohortMemberSpec, ...] = Field(
        min_length=1,
        max_length=MAX_CALIBRATION_COHORT_MEMBERS,
    )

    @field_validator("fanout_scope")
    @classmethod
    def validate_fanout_scope(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration fanout scope")

    @field_validator("evaluated_at")
    @classmethod
    def canonicalize_evaluated_at(cls, value: datetime) -> datetime:
        return _canonical_utc(value, field_name="evaluated_at")

    @model_validator(mode="after")
    def validate_spec(self) -> CalibrationCohortSpec:
        if self.observed_fanout_active_count + len(self.members) > self.max_in_flight:
            raise ValueError(
                "calibration cohort members exceed observed fanout capacity"
            )
        _require_unique(
            (observation.calibration_key for observation in self.observations),
            label="calibration cohort observation key",
        )
        _require_unique(
            (member.member_id for member in self.members),
            label="calibration cohort member id",
        )
        _require_unique(
            (member.calibration_key for member in self.members),
            label="calibration cohort member key",
        )

        observations_by_key = {
            observation.calibration_key: observation
            for observation in self.observations
        }
        for member in self.members:
            if member.definition != self.planner:
                raise ValueError(
                    "calibration cohort members must use its planner definition"
                )
            observation = observations_by_key.get(member.calibration_key)
            if observation is None:
                raise ValueError(
                    "cohort observations must cover every member calibration key"
                )
            _validate_member_due_observation(member, observation)
            for reason in member.due_reasons:
                if (
                    isinstance(reason, CalibrationExpiredDueReason)
                    and reason.expired_at > self.evaluated_at
                ):
                    raise ValueError(
                        "expired calibration must be due by cohort evaluation"
                    )
            for dependency in member.dependencies:
                if dependency.succeeded_at > self.evaluated_at:
                    raise ValueError(
                        "cohort dependency success cannot follow its evaluation"
                    )
                dependency_observation = observations_by_key.get(
                    dependency.calibration_key
                )
                if dependency_observation is None:
                    raise ValueError(
                        "cohort observations must cover every dependency key"
                    )
                latest_success = dependency_observation.latest_success
                if (
                    latest_success is None
                    or latest_success.dependency_evidence != dependency
                ):
                    raise ValueError(
                        "member dependency must equal observed latest success"
                    )
        return self


def calibration_cohort_spec_hash(
    spec: CalibrationCohortSpec,
) -> Sha256ContentHash:
    """Hash the complete immutable cohort decision, excluding caller identity."""

    digest = stable_content_hash(
        {
            "codec": _CALIBRATION_COHORT_SPEC_CODEC,
            "spec": spec.model_dump(mode="json"),
        }
    )
    return f"sha256:{digest}"


class CalibrationCohort(_CalibrationModel):
    """Durable immutable cohort accepted under a caller-owned identity."""

    cohort_id: _NonEmptyText
    spec: CalibrationCohortSpec
    spec_hash: Sha256ContentHash
    created_at: datetime

    @field_validator("cohort_id")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration cohort id")

    @field_validator("created_at")
    @classmethod
    def canonicalize_created_at(cls, value: datetime) -> datetime:
        return _canonical_utc(value, field_name="created_at")

    @model_validator(mode="after")
    def validate_spec_hash(self) -> CalibrationCohort:
        if self.spec_hash != calibration_cohort_spec_hash(self.spec):
            raise ValueError("calibration cohort spec hash must cover its exact spec")
        if self.created_at < self.spec.evaluated_at:
            raise ValueError("calibration cohort cannot precede its evaluation")
        if any(
            dependency.cohort_id == self.cohort_id
            for member in self.spec.members
            for dependency in member.dependencies
        ):
            raise ValueError(
                "calibration cohort cannot consume a same-cohort dependency"
            )
        return self


class CalibrationCohortSummary(_CalibrationModel):
    """Bounded list projection without repeating the complete member specs."""

    cohort_id: _NonEmptyText
    planner: CalibrationDefinitionRef
    fanout_scope: _NonEmptyText
    spec_hash: Sha256ContentHash
    member_count: int = Field(ge=1, le=MAX_CALIBRATION_COHORT_MEMBERS)
    evaluated_at: datetime
    created_at: datetime

    @field_validator("cohort_id", "fanout_scope")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _non_blank(value, field_name="calibration cohort summary identity")

    @field_validator("evaluated_at", "created_at")
    @classmethod
    def canonicalize_time(cls, value: datetime, info: ValidationInfo) -> datetime:
        return _canonical_utc(
            value,
            field_name=info.field_name or "calibration cohort time",
        )

    @classmethod
    def from_cohort(cls, cohort: CalibrationCohort) -> CalibrationCohortSummary:
        return cls(
            cohort_id=cohort.cohort_id,
            planner=cohort.spec.planner,
            fanout_scope=cohort.spec.fanout_scope,
            spec_hash=cohort.spec_hash,
            member_count=len(cohort.spec.members),
            evaluated_at=cohort.spec.evaluated_at,
            created_at=cohort.created_at,
        )


def _success_from_attempt_status(
    status: CalibrationAttemptStatus,
) -> CalibrationSuccessRef | None:
    if (
        status.procedure_state != "closed"
        or status.closure is None
        or status.closure.status != "succeeded"
    ):
        return None
    return CalibrationSuccessRef(
        attempt=status.attempt,
        succeeded_at=status.closure.closed_at,
    )


def _validate_member_due_observation(
    member: CalibrationCohortMemberSpec,
    observation: CalibrationStatus,
) -> None:
    latest_success = observation.latest_success
    previous_dependencies = (
        {}
        if latest_success is None
        else {
            dependency.calibration_key: dependency
            for dependency in latest_success.attempt.dependencies
        }
    )
    current_dependencies = {
        dependency.calibration_key: dependency for dependency in member.dependencies
    }
    for reason in member.due_reasons:
        if isinstance(reason, CalibrationMissingSuccessDueReason):
            if latest_success is not None:
                raise ValueError(
                    "missing-success due reason requires no observed success"
                )
        elif isinstance(reason, CalibrationExpiredDueReason):
            if reason.previous_success != latest_success:
                raise ValueError(
                    "member due reason must reference observed latest success"
                )
        elif isinstance(reason, CalibrationDefinitionChangedDueReason):
            if reason.previous_success != latest_success:
                raise ValueError(
                    "member due reason must reference observed latest success"
                )
            previous = reason.previous_success.attempt
            if (
                previous.definition == member.definition
                and previous.procedure == member.procedure
            ):
                raise ValueError(
                    "definition-changed due reason requires a prior definition "
                    "or procedure change"
                )
        elif isinstance(reason, CalibrationInputsChangedDueReason):
            if reason.previous_success != latest_success:
                raise ValueError(
                    "member due reason must reference observed latest success"
                )
            if (
                reason.previous_success.attempt.input_fingerprint
                == member.input_fingerprint
            ):
                raise ValueError(
                    "inputs-changed due reason requires a prior input change"
                )
        elif isinstance(reason, CalibrationDependencyChangedDueReason):
            if latest_success is None:
                raise ValueError(
                    "dependency-changed due reason requires an observed latest success"
                )
            if reason.previous_success != previous_dependencies.get(
                reason.dependency_key
            ):
                raise ValueError(
                    "dependency-changed due reason must reference observed prior "
                    "dependency evidence"
                )
            if reason.current_success != current_dependencies.get(
                reason.dependency_key
            ):
                raise ValueError(
                    "dependency-changed due reason must reference current member "
                    "dependency evidence"
                )


def _canonical_dependencies(
    dependencies: tuple[CalibrationDependencyEvidence, ...],
    *,
    label: str,
) -> tuple[CalibrationDependencyEvidence, ...]:
    _require_unique(
        (dependency.calibration_key for dependency in dependencies),
        label=label,
    )
    return tuple(
        sorted(dependencies, key=lambda dependency: dependency.calibration_key)
    )


def _canonical_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


def _non_blank(value: str, *, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _require_unique(values: Iterable[Hashable], *, label: str) -> None:
    selected = tuple(values)
    if len(selected) != len(set(selected)):
        raise ValueError(f"{label}s must be unique")


__all__ = [
    "MAX_CALIBRATION_COHORT_MEMBERS",
    "MAX_CALIBRATION_STATUS_KEYS",
    "CalibrationAttemptRef",
    "CalibrationAttemptStatus",
    "CalibrationCohort",
    "CalibrationCohortMember",
    "CalibrationCohortMemberSpec",
    "CalibrationCohortSpec",
    "CalibrationCohortSummary",
    "CalibrationConfigSourceRef",
    "CalibrationDefinitionChangedDueReason",
    "CalibrationDefinitionRef",
    "CalibrationDependencyChangedDueReason",
    "CalibrationDependencyEvidence",
    "CalibrationDueReason",
    "CalibrationExpiredDueReason",
    "CalibrationForcedDueReason",
    "CalibrationInputsChangedDueReason",
    "CalibrationMissingSuccessDueReason",
    "CalibrationStatus",
    "CalibrationStatusSnapshot",
    "CalibrationSuccessRef",
    "CalibrationTargetRef",
    "calibration_cohort_member_request_key",
    "calibration_cohort_spec_hash",
    "calibration_freshness_fingerprint",
    "calibration_key",
]

"""Project-owned fixed-UTC interval definitions for exact one-shot schedules."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Annotated, Literal, Protocol, cast, get_type_hints, override

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.automation.definition import ProcedureDefinition, RegisteredProcedure
from scopecat.kernel.content_identity import stable_content_hash

type _NonEmptyText = Annotated[str, Field(min_length=1)]

_INTERVAL_OCCURRENCE_SCHEDULE_ID_CODEC = "scopecat.interval-occurrence.v1"
MAX_PROCEDURE_SCHEDULE_REGISTRY_SIZE = 200


class _IntervalModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class IntervalTrigger(_IntervalModel):
    """A timezone-independent fixed interval anchored at one UTC instant."""

    anchor: datetime
    every: timedelta

    @field_validator("anchor")
    @classmethod
    def canonicalize_anchor(cls, value: datetime) -> datetime:
        return _canonical_utc(value, field_name="interval anchor")

    @field_validator("every")
    @classmethod
    def validate_every(cls, value: timedelta) -> timedelta:
        if value <= timedelta(0):
            raise ValueError("interval duration must be positive")
        return value

    def latest_ordinal(self, at: datetime) -> int | None:
        """Select only the latest due ordinal in O(1), never a catch-up range."""

        selected = _canonical_utc(at, field_name="interval evaluation time")
        if selected < self.anchor:
            return None
        return (selected - self.anchor) // self.every

    def due_at(self, ordinal: int) -> datetime:
        """Resolve one non-negative ordinal using exact timedelta arithmetic."""

        if ordinal < 0:
            raise ValueError("interval occurrence ordinal must be non-negative")
        return self.anchor + self.every * ordinal


def interval_occurrence_schedule_id(
    schedule_definition_id: str,
    schedule_definition_version: str,
    ordinal: int,
) -> str:
    """Identify one logical interval slot independently of mutable intent code."""

    selected_id = _non_blank(
        schedule_definition_id,
        field_name="procedure schedule definition id",
    )
    selected_version = _non_blank(
        schedule_definition_version,
        field_name="procedure schedule definition version",
    )
    if ordinal < 0:
        raise ValueError("interval occurrence ordinal must be non-negative")
    digest = stable_content_hash(
        {
            "codec": _INTERVAL_OCCURRENCE_SCHEDULE_ID_CODEC,
            "schedule_definition_id": selected_id,
            "schedule_definition_version": selected_version,
            "ordinal": ordinal,
        }
    )
    return f"procedure-interval:{digest}"


class IntervalOccurrence(_IntervalModel):
    """One deterministic logical slot selected from an interval definition."""

    schedule_id: _NonEmptyText
    schedule_definition_id: _NonEmptyText
    schedule_definition_version: _NonEmptyText
    ordinal: int = Field(ge=0)
    due_at: datetime

    @field_validator(
        "schedule_id",
        "schedule_definition_id",
        "schedule_definition_version",
    )
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _non_blank(value, field_name="interval occurrence identity")

    @field_validator("due_at")
    @classmethod
    def canonicalize_due_at(cls, value: datetime) -> datetime:
        return _canonical_utc(value, field_name="interval occurrence due_at")

    @model_validator(mode="after")
    def validate_schedule_id(self) -> IntervalOccurrence:
        expected = interval_occurrence_schedule_id(
            self.schedule_definition_id,
            self.schedule_definition_version,
            self.ordinal,
        )
        if self.schedule_id != expected:
            raise ValueError(
                "interval occurrence schedule_id must identify its logical slot"
            )
        return self


class RegisteredProcedureSchedule[ContextT](Protocol):
    """Type-erased interval definition retained by a heterogeneous registry."""

    @property
    def id(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def procedure(self) -> RegisteredProcedure: ...

    @property
    def trigger(self) -> IntervalTrigger: ...

    @property
    def overlap_policy(self) -> Literal["enqueue"]: ...

    def latest_occurrence(self, at: datetime) -> IntervalOccurrence | None: ...

    def build_intent(
        self,
        context: ContextT,
        occurrence: IntervalOccurrence,
    ) -> BaseModel: ...


@dataclass(frozen=True, slots=True, repr=False)
class ProcedureScheduleDefinition[ContextT, IntentT: BaseModel]:
    """One typed project-side interval policy targeting an exact procedure."""

    id: str
    version: str
    procedure: ProcedureDefinition[IntentT]
    trigger: IntervalTrigger
    _build_intent: Callable[[ContextT, IntervalOccurrence], IntentT] = field(
        repr=False,
        compare=False,
    )
    overlap_policy: Literal["enqueue"] = "enqueue"

    def __post_init__(self) -> None:
        _non_blank(self.id, field_name="procedure schedule definition id")
        _non_blank(self.version, field_name="procedure schedule definition version")
        if self.overlap_policy != "enqueue":
            raise ValueError("only the enqueue interval overlap policy is supported")
        _validate_intent_builder(self._build_intent, self.procedure.intent_type)

    def latest_occurrence(self, at: datetime) -> IntervalOccurrence | None:
        ordinal = self.trigger.latest_ordinal(at)
        if ordinal is None:
            return None
        return IntervalOccurrence(
            schedule_id=interval_occurrence_schedule_id(
                self.id,
                self.version,
                ordinal,
            ),
            schedule_definition_id=self.id,
            schedule_definition_version=self.version,
            ordinal=ordinal,
            due_at=self.trigger.due_at(ordinal),
        )

    def build_intent(
        self,
        context: ContextT,
        occurrence: IntervalOccurrence,
    ) -> IntentT:
        """Build and validate intent after absence of the one-shot is known."""

        expected = self.latest_occurrence(occurrence.due_at)
        if expected != occurrence:
            raise ValueError(
                "interval occurrence does not belong to this schedule definition"
            )
        return self.procedure.validate_intent(self._build_intent(context, occurrence))


def interval_schedule[ContextT, IntentT: BaseModel](
    *,
    id: str,
    version: str,
    procedure: ProcedureDefinition[IntentT],
    trigger: IntervalTrigger,
    overlap_policy: Literal["enqueue"] = "enqueue",
) -> Callable[
    [Callable[[ContextT, IntervalOccurrence], IntentT]],
    ProcedureScheduleDefinition[ContextT, IntentT],
]:
    """Decorate one context-aware intent builder as an interval definition."""

    def decorate(
        builder: Callable[[ContextT, IntervalOccurrence], IntentT],
    ) -> ProcedureScheduleDefinition[ContextT, IntentT]:
        return ProcedureScheduleDefinition(
            id=id,
            version=version,
            procedure=procedure,
            trigger=trigger,
            _build_intent=builder,
            overlap_policy=overlap_policy,
        )

    return decorate


class ProcedureScheduleRegistry[ContextT](
    Mapping[str, RegisteredProcedureSchedule[ContextT]]
):
    """Immutable registry with one active version per logical schedule ID."""

    __slots__ = ("_definitions",)

    _definitions: Mapping[str, RegisteredProcedureSchedule[ContextT]]

    def __init__(
        self,
        definitions: Iterable[RegisteredProcedureSchedule[ContextT]] = (),
    ) -> None:
        selected: dict[str, RegisteredProcedureSchedule[ContextT]] = {}
        for definition in definitions:
            if definition.id in selected:
                existing = selected[definition.id]
                raise ValueError(
                    f"procedure schedule {definition.id!r} has more than one active "
                    f"version ({existing.version!r} and {definition.version!r})"
                )
            if len(selected) >= MAX_PROCEDURE_SCHEDULE_REGISTRY_SIZE:
                raise ValueError(
                    "procedure schedule registry supports at most "
                    f"{MAX_PROCEDURE_SCHEDULE_REGISTRY_SIZE} definitions"
                )
            selected[definition.id] = definition
        self._definitions = MappingProxyType(dict(sorted(selected.items())))

    @override
    def __getitem__(self, key: str) -> RegisteredProcedureSchedule[ContextT]:
        return self._definitions[key]

    @override
    def __iter__(self) -> Iterator[str]:
        return iter(self._definitions)

    @override
    def __len__(self) -> int:
        return len(self._definitions)

    def require(self, id: str) -> RegisteredProcedureSchedule[ContextT]:
        try:
            return self._definitions[id]
        except KeyError as error:
            raise LookupError(f"no procedure schedule {id!r} is registered") from error


def _validate_intent_builder(
    builder: Callable[..., BaseModel],
    intent_type: type[BaseModel],
) -> None:
    if not inspect.isfunction(builder):
        raise TypeError("procedure schedule intent builder must be a Python function")
    if inspect.iscoroutinefunction(builder):
        raise TypeError("procedure schedule intent builder must be synchronous")
    signature = inspect.signature(builder)
    parameters = tuple(signature.parameters.values())
    if len(parameters) != 2 or any(
        parameter.kind
        not in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
        or cast("object", parameter.default) is not inspect.Parameter.empty
        for parameter in parameters
    ):
        raise TypeError(
            "procedure schedule intent builder requires exactly (context, occurrence)"
        )
    try:
        hints = get_type_hints(builder)
    except (NameError, TypeError) as error:
        raise TypeError(
            "procedure schedule intent builder annotations must be resolvable"
        ) from error
    context_parameter, occurrence_parameter = parameters
    if context_parameter.name not in hints:
        raise TypeError("procedure schedule planning context requires an annotation")
    if hints.get(occurrence_parameter.name) is not IntervalOccurrence:
        raise TypeError(
            "procedure schedule occurrence annotation must be IntervalOccurrence"
        )
    if hints.get("return", inspect.Signature.empty) is not intent_type:
        raise TypeError(
            "procedure schedule intent builder return annotation must match the "
            "procedure intent model"
        )


def _canonical_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


def _non_blank(value: str, *, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


__all__ = [
    "MAX_PROCEDURE_SCHEDULE_REGISTRY_SIZE",
    "IntervalOccurrence",
    "IntervalTrigger",
    "ProcedureScheduleDefinition",
    "ProcedureScheduleRegistry",
    "RegisteredProcedureSchedule",
    "interval_occurrence_schedule_id",
    "interval_schedule",
]

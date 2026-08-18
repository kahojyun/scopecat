from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from scopecat.automation import (
    IntervalOccurrence,
    IntervalTrigger,
    ProcedureScheduleDefinition,
    ProcedureScheduleRegistry,
    interval_occurrence_schedule_id,
    interval_schedule,
    procedure,
)


class _IntervalIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class _PlanningContext:
    source: str


@procedure(id="tests.interval-target", version="1", intent=_IntervalIntent)
def _target(_context: object, _intent: _IntervalIntent) -> None:
    pass


@procedure(id="tests.changed-interval-target", version="2", intent=_IntervalIntent)
def _changed_target(_context: object, _intent: _IntervalIntent) -> None:
    pass


def _build_intent(
    context: _PlanningContext,
    occurrence: IntervalOccurrence,
) -> _IntervalIntent:
    return _IntervalIntent(source=context.source, ordinal=occurrence.ordinal)


_ANCHOR = datetime(2026, 8, 18, 0, 0, tzinfo=UTC)
_TRIGGER = IntervalTrigger(anchor=_ANCHOR, every=timedelta(hours=6))


def _definition(
    *,
    id: str = "tests.nightly",
    version: str = "1",
) -> ProcedureScheduleDefinition[_PlanningContext, _IntervalIntent]:
    return ProcedureScheduleDefinition(
        id=id,
        version=version,
        procedure=_target,
        trigger=_TRIGGER,
        _build_intent=_build_intent,
    )


def test_interval_trigger_selects_only_the_latest_due_ordinal() -> None:
    trigger = IntervalTrigger(
        anchor=datetime(2026, 8, 18, 8, 0, tzinfo=timezone(timedelta(hours=8))),
        every=timedelta(minutes=90),
    )

    assert trigger.anchor == _ANCHOR
    assert trigger.latest_ordinal(_ANCHOR - timedelta(microseconds=1)) is None
    assert trigger.latest_ordinal(_ANCHOR) == 0
    assert trigger.latest_ordinal(_ANCHOR + timedelta(hours=7)) == 4
    assert trigger.due_at(4) == _ANCHOR + timedelta(hours=6)


def test_interval_occurrence_identity_uses_only_logical_id_version_and_ordinal() -> (
    None
):
    expected = interval_occurrence_schedule_id("tests.nightly", "1", 7)
    changed_trigger = IntervalTrigger(
        anchor=_ANCHOR - timedelta(days=1),
        every=timedelta(hours=3),
    )
    changed_definition = ProcedureScheduleDefinition(
        id="tests.nightly",
        version="1",
        procedure=_changed_target,
        trigger=changed_trigger,
        _build_intent=_build_intent,
    )

    assert interval_occurrence_schedule_id("tests.nightly", "1", 7) == expected
    assert changed_definition.latest_occurrence(
        changed_trigger.due_at(7)
    ) == IntervalOccurrence(
        schedule_id=expected,
        schedule_definition_id="tests.nightly",
        schedule_definition_version="1",
        ordinal=7,
        due_at=changed_trigger.due_at(7),
    )
    assert interval_occurrence_schedule_id("tests.nightly", "2", 7) != expected
    assert interval_occurrence_schedule_id("tests.other", "1", 7) != expected
    assert interval_occurrence_schedule_id("tests.nightly", "1", 8) != expected


def test_schedule_definition_builds_typed_intent_for_its_exact_occurrence() -> None:
    definition = _definition()
    occurrence = definition.latest_occurrence(_ANCHOR + timedelta(hours=14))

    assert occurrence is not None
    assert occurrence.ordinal == 2
    assert occurrence.due_at == _ANCHOR + timedelta(hours=12)
    assert definition.build_intent(
        _PlanningContext(source="active-generation-9"),
        occurrence,
    ) == _IntervalIntent(source="active-generation-9", ordinal=2)

    foreign = occurrence.model_copy(
        update={
            "schedule_definition_id": "tests.other",
            "schedule_id": interval_occurrence_schedule_id("tests.other", "1", 2),
        }
    )
    with pytest.raises(ValueError, match="does not belong"):
        definition.build_intent(_PlanningContext(source="active"), foreign)


def test_interval_schedule_decorator_preserves_builder_contract() -> None:
    @interval_schedule(
        id="tests.decorated",
        version="1",
        procedure=_target,
        trigger=_TRIGGER,
    )
    def decorated(
        context: _PlanningContext,
        occurrence: IntervalOccurrence,
    ) -> _IntervalIntent:
        return _IntervalIntent(source=context.source, ordinal=occurrence.ordinal)

    occurrence = decorated.latest_occurrence(_ANCHOR)

    assert occurrence is not None
    assert decorated.build_intent(_PlanningContext("active"), occurrence).source == (
        "active"
    )


def test_schedule_registry_allows_only_one_active_version_per_logical_id() -> None:
    first = _definition(version="1")
    second = _definition(version="2")

    with pytest.raises(ValueError, match="more than one active version"):
        ProcedureScheduleRegistry((first, second))

    registry = ProcedureScheduleRegistry(
        (_definition(id="tests.z"), _definition(id="tests.a"))
    )
    assert tuple(registry) == ("tests.a", "tests.z")
    assert registry.require("tests.a").id == "tests.a"


def test_interval_models_reject_naive_or_invalid_values() -> None:
    with pytest.raises(ValidationError, match="UTC offset"):
        IntervalTrigger(anchor=_ANCHOR.replace(tzinfo=None), every=timedelta(hours=1))
    with pytest.raises(ValidationError, match="must be positive"):
        IntervalTrigger(anchor=_ANCHOR, every=timedelta(0))
    with pytest.raises(ValueError, match="non-negative"):
        _TRIGGER.due_at(-1)
    with pytest.raises(ValueError, match="non-negative"):
        interval_occurrence_schedule_id("tests.nightly", "1", -1)
    with pytest.raises(ValidationError, match="logical slot"):
        IntervalOccurrence(
            schedule_id="wrong",
            schedule_definition_id="tests.nightly",
            schedule_definition_version="1",
            ordinal=0,
            due_at=_ANCHOR,
        )


def test_intent_builder_requires_resolvable_exact_annotations() -> None:
    def invalid_builder(
        context: _PlanningContext,
        occurrence: object,
    ) -> _IntervalIntent:
        del occurrence
        return _IntervalIntent(source=context.source, ordinal=0)

    with pytest.raises(TypeError, match="occurrence annotation"):
        ProcedureScheduleDefinition(
            id="tests.invalid",
            version="1",
            procedure=_target,
            trigger=_TRIGGER,
            _build_intent=invalid_builder,  # type: ignore[arg-type]
        )

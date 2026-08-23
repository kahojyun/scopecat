"""Bounded real-time control at the quantum target boundary.

The core pulse scheduler produces canonical :class:`ScheduledPulseProgram`
blocks.  This module composes those blocks without flattening target-visible
conditionals or fixed repeats.  A laboratory target compiler can therefore
decide which feedback predicates, branch timings, and loop forms its hardware
supports while Scopecat can still prove a finite resource and result envelope.

Conditional branches deliberately cannot acquire results.  Measurements may
precede a conditional, follow it, or appear in the next fixed round.  Keeping
acquisition shape independent of the selected branch makes result addressing
static while still covering active reset and syndrome-driven correction.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal

from scopecat_quantum._ids import AcquisitionSlotId, PulseEventId, PulseProgramId
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.pulses import (
    AcquisitionSlot,
    LogicalSignal,
    ScheduledPulseEvent,
    ScheduledPulseProgram,
)

type RealtimePathItem = str | int


@dataclass(frozen=True, slots=True)
class ScheduledBlock:
    """One statically scheduled leaf in a target program."""

    program: ScheduledPulseProgram


@dataclass(frozen=True, slots=True)
class RealtimeNoOp:
    """An explicit empty branch, commonly the default of active reset."""


@dataclass(frozen=True, slots=True)
class ClassifiedStatePredicate:
    """Read the integer state produced by one earlier classified acquisition."""

    slot_id: AcquisitionSlotId


@dataclass(frozen=True, slots=True)
class RealtimeCase:
    """One equality case in a classified-state conditional."""

    state: int
    body: RealtimeInstruction

    def __post_init__(self) -> None:
        if type(self.state) is not int:
            raise ValueError("real-time case state must be an integer")


@dataclass(frozen=True, slots=True)
class RealtimeConditional:
    """A finite target-visible switch with a total default branch."""

    predicate: ClassifiedStatePredicate
    cases: tuple[RealtimeCase, ...]
    default: RealtimeInstruction

    def __post_init__(self) -> None:
        if not self.cases:
            raise ValueError("real-time conditionals require at least one case")
        states = tuple(case.state for case in self.cases)
        if len(set(states)) != len(states):
            raise ValueError("real-time conditional case states must be unique")


@dataclass(frozen=True, slots=True)
class RealtimeSequence:
    """Execute bounded real-time instructions in order."""

    instructions: tuple[RealtimeInstruction, ...]


@dataclass(frozen=True, slots=True)
class RealtimeRepeat:
    """Repeat one bounded instruction a fixed positive number of times.

    A result-producing repeat names the local result dimension receiving the
    iterations.  Every acquisition in the body must declare that dimension
    with ``size == count``.  A result-free repeat leaves the field unset.
    """

    instruction: RealtimeInstruction
    count: int
    result_dimension_id: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.count, bool) or self.count <= 0:
            raise ValueError("real-time repeat count must be a positive finite integer")
        if (
            self.result_dimension_id is not None
            and not self.result_dimension_id.strip()
        ):
            raise ValueError("real-time repeat result dimension id must be non-empty")


type RealtimeInstruction = (
    ScheduledBlock
    | RealtimeNoOp
    | RealtimeConditional
    | RealtimeSequence
    | RealtimeRepeat
)


@dataclass(frozen=True, slots=True)
class RealtimeProgramIssue:
    """One deterministic static failure in a target program."""

    code: str
    message: str
    path: tuple[RealtimePathItem, ...] = ()


class RealtimeProgramValidationError(ValueError):
    """Aggregate of independently discoverable target-program failures."""

    __slots__ = ("issues",)

    def __init__(self, issues: Iterable[RealtimeProgramIssue]) -> None:
        selected = tuple(issues)
        if not selected:
            raise ValueError("real-time validation errors require at least one issue")
        self.issues = tuple(
            sorted(
                selected,
                key=lambda issue: (
                    tuple(str(item) for item in issue.path),
                    issue.code,
                    issue.message,
                ),
            )
        )
        super().__init__(
            "; ".join(f"{issue.code}: {issue.message}" for issue in self.issues)
        )


@dataclass(frozen=True, slots=True)
class RealtimeEvent:
    """One structural scheduled event retained in the target-program union."""

    path: tuple[RealtimePathItem, ...]
    event: ScheduledPulseEvent


@dataclass(frozen=True, slots=True)
class TargetProgramEnvelope:
    """Finite, hardware-neutral bounds and unions for one target program.

    Durations include scheduled pulse blocks but not target-owned branch or
    loop-dispatch latency.  Operation counts include scheduled pulse events and
    conditional decisions; structural sequence and repeat nodes add no count.
    Event and signal inventories are structural unions, so a repeat retains one
    copy while its worst-case counts and durations include every iteration.
    """

    minimum_duration_seconds: Decimal
    worst_case_duration_seconds: Decimal
    worst_case_operation_count: int
    worst_case_acquisition_count: int
    acquisition_slots: tuple[AcquisitionSlot, ...]
    logical_signals: tuple[LogicalSignal, ...]
    events: tuple[RealtimeEvent, ...]

    @property
    def has_variable_duration(self) -> bool:
        """Whether runtime predicate outcomes can change scheduled duration."""

        return self.minimum_duration_seconds != self.worst_case_duration_seconds

    @property
    def pulse_event_ids(self) -> tuple[PulseEventId, ...]:
        """Return first-seen pulse-event identities across the structural union."""

        return _unique(event.event.id for event in self.events)


@dataclass(frozen=True, slots=True)
class TargetProgram:
    """A statically bounded program presented to a quantum target compiler."""

    id: PulseProgramId
    body: RealtimeInstruction
    envelope: TargetProgramEnvelope = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "envelope", _analyze_target_program(self.body))

    @classmethod
    def from_scheduled(cls, program: ScheduledPulseProgram) -> TargetProgram:
        """Lift an ordinary static schedule into the target-program model."""

        return cls(id=program.id, body=ScheduledBlock(program))

    @property
    def acquisition_slots(self) -> tuple[AcquisitionSlot, ...]:
        """Return the exact static result-slot union."""

        return self.envelope.acquisition_slots


@dataclass(frozen=True, slots=True)
class _Profile:
    minimum_duration_seconds: Decimal
    worst_case_duration_seconds: Decimal
    worst_case_operation_count: int
    worst_case_acquisition_count: int
    acquisition_slots: tuple[AcquisitionSlot, ...]
    logical_signals: tuple[LogicalSignal, ...]
    events: tuple[RealtimeEvent, ...]


_EMPTY_PROFILE = _Profile(
    minimum_duration_seconds=Decimal(0),
    worst_case_duration_seconds=Decimal(0),
    worst_case_operation_count=0,
    worst_case_acquisition_count=0,
    acquisition_slots=(),
    logical_signals=(),
    events=(),
)


def _unique[T](values: Iterable[T]) -> tuple[T, ...]:
    selected: list[T] = []
    seen: set[T] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        selected.append(value)
    return tuple(selected)


def _analyze_target_program(body: RealtimeInstruction) -> TargetProgramEnvelope:
    issues: list[RealtimeProgramIssue] = []
    profile = _profile(body, path=())
    slot_index: dict[AcquisitionSlotId, AcquisitionSlot] = {}
    for slot in profile.acquisition_slots:
        if slot.id in slot_index:
            issues.append(
                RealtimeProgramIssue(
                    code="realtime_acquisition_slot_duplicate",
                    message=(
                        f"acquisition slot {slot.id.qualified_name!r} is declared "
                        "by more than one scheduled block"
                    ),
                )
            )
            continue
        slot_index[slot.id] = slot
    event_index: dict[PulseEventId, RealtimeEvent] = {}
    for realtime_event in profile.events:
        if realtime_event.event.id in event_index:
            issues.append(
                RealtimeProgramIssue(
                    code="realtime_pulse_event_duplicate",
                    message=(
                        f"pulse event {realtime_event.event.id.qualified_name!r} "
                        "is declared by more than one scheduled block"
                    ),
                    path=realtime_event.path,
                )
            )
            continue
        event_index[realtime_event.event.id] = realtime_event
    _validate_dataflow(
        body,
        path=(),
        available={},
        active_result_dimensions=frozenset(),
        slot_index=slot_index,
        issues=issues,
        inside_conditional_branch=False,
    )
    if issues:
        raise RealtimeProgramValidationError(issues)
    return TargetProgramEnvelope(
        minimum_duration_seconds=profile.minimum_duration_seconds,
        worst_case_duration_seconds=profile.worst_case_duration_seconds,
        worst_case_operation_count=profile.worst_case_operation_count,
        worst_case_acquisition_count=profile.worst_case_acquisition_count,
        acquisition_slots=profile.acquisition_slots,
        logical_signals=_unique(profile.logical_signals),
        events=profile.events,
    )


def _profile(
    instruction: RealtimeInstruction,
    *,
    path: tuple[RealtimePathItem, ...],
) -> _Profile:
    if isinstance(instruction, RealtimeNoOp):
        return _EMPTY_PROFILE
    if isinstance(instruction, ScheduledBlock):
        program = instruction.program
        events = tuple(
            RealtimeEvent((*path, "events", index), event)
            for index, event in enumerate(program.events)
        )
        return _Profile(
            minimum_duration_seconds=program.duration_seconds,
            worst_case_duration_seconds=program.duration_seconds,
            worst_case_operation_count=len(program.events),
            worst_case_acquisition_count=len(program.acquisition_slots),
            acquisition_slots=program.acquisition_slots,
            logical_signals=tuple(event.instruction.signal for event in program.events),
            events=events,
        )
    if isinstance(instruction, RealtimeSequence):
        profiles = tuple(
            _profile(child, path=(*path, "sequence", index))
            for index, child in enumerate(instruction.instructions)
        )
        return _sequence_profile(profiles)
    if isinstance(instruction, RealtimeRepeat):
        profile = _profile(instruction.instruction, path=(*path, "repeat"))
        return _Profile(
            minimum_duration_seconds=(
                profile.minimum_duration_seconds * instruction.count
            ),
            worst_case_duration_seconds=(
                profile.worst_case_duration_seconds * instruction.count
            ),
            worst_case_operation_count=(
                profile.worst_case_operation_count * instruction.count
            ),
            worst_case_acquisition_count=(
                profile.worst_case_acquisition_count * instruction.count
            ),
            acquisition_slots=profile.acquisition_slots,
            logical_signals=profile.logical_signals,
            events=profile.events,
        )
    profiles = tuple(
        _profile(case.body, path=(*path, "cases", case.state))
        for case in instruction.cases
    )
    default_profile = _profile(instruction.default, path=(*path, "default"))
    branches = (*profiles, default_profile)
    return _Profile(
        minimum_duration_seconds=min(
            profile.minimum_duration_seconds for profile in branches
        ),
        worst_case_duration_seconds=max(
            profile.worst_case_duration_seconds for profile in branches
        ),
        worst_case_operation_count=(
            1 + max(profile.worst_case_operation_count for profile in branches)
        ),
        worst_case_acquisition_count=max(
            profile.worst_case_acquisition_count for profile in branches
        ),
        acquisition_slots=tuple(
            slot for profile in branches for slot in profile.acquisition_slots
        ),
        logical_signals=tuple(
            signal for profile in branches for signal in profile.logical_signals
        ),
        events=tuple(event for profile in branches for event in profile.events),
    )


def _sequence_profile(profiles: tuple[_Profile, ...]) -> _Profile:
    return _Profile(
        minimum_duration_seconds=sum(
            (profile.minimum_duration_seconds for profile in profiles),
            start=Decimal(0),
        ),
        worst_case_duration_seconds=sum(
            (profile.worst_case_duration_seconds for profile in profiles),
            start=Decimal(0),
        ),
        worst_case_operation_count=sum(
            profile.worst_case_operation_count for profile in profiles
        ),
        worst_case_acquisition_count=sum(
            profile.worst_case_acquisition_count for profile in profiles
        ),
        acquisition_slots=tuple(
            slot for profile in profiles for slot in profile.acquisition_slots
        ),
        logical_signals=tuple(
            signal for profile in profiles for signal in profile.logical_signals
        ),
        events=tuple(event for profile in profiles for event in profile.events),
    )


def _validate_repeat_shape(
    repeat: RealtimeRepeat,
    profile: _Profile,
    *,
    path: tuple[RealtimePathItem, ...],
    active_result_dimensions: frozenset[str],
    issues: list[RealtimeProgramIssue],
) -> frozenset[str]:
    dimension_id = repeat.result_dimension_id
    if profile.acquisition_slots and dimension_id is None:
        issues.append(
            RealtimeProgramIssue(
                code="realtime_repeat_result_dimension_missing",
                message=(
                    "result-producing real-time repeats must name their local "
                    "result dimension"
                ),
                path=path,
            )
        )
    if not profile.acquisition_slots and dimension_id is not None:
        issues.append(
            RealtimeProgramIssue(
                code="realtime_repeat_result_dimension_unused",
                message="result-free real-time repeats cannot name a result dimension",
                path=path,
            )
        )
    if dimension_id is None:
        return active_result_dimensions
    for slot in profile.acquisition_slots:
        dimension = next(
            (
                dimension
                for dimension in slot.contract.dimensions
                if dimension.id == dimension_id
            ),
            None,
        )
        if dimension is None or dimension.size != repeat.count:
            issues.append(
                RealtimeProgramIssue(
                    code="realtime_repeat_result_dimension_mismatch",
                    message=(
                        f"acquisition slot {slot.id.qualified_name!r} must declare "
                        f"dimension {dimension_id!r} with size {repeat.count}"
                    ),
                    path=path,
                )
            )
    if dimension_id in active_result_dimensions:
        issues.append(
            RealtimeProgramIssue(
                code="realtime_repeat_result_dimension_reentered",
                message=(
                    f"result dimension {dimension_id!r} cannot identify nested "
                    "real-time repeats"
                ),
                path=path,
            )
        )
    return active_result_dimensions | {dimension_id}


def _validate_predicate(
    predicate: ClassifiedStatePredicate,
    *,
    path: tuple[RealtimePathItem, ...],
    available: dict[AcquisitionSlotId, frozenset[str]],
    active_result_dimensions: frozenset[str],
    slot_index: dict[AcquisitionSlotId, AcquisitionSlot],
    issues: list[RealtimeProgramIssue],
) -> None:
    predicate_id = predicate.slot_id
    slot = slot_index.get(predicate_id)
    if slot is None:
        issues.append(
            RealtimeProgramIssue(
                code="realtime_predicate_unknown_slot",
                message=(
                    f"predicate references undeclared acquisition slot "
                    f"{predicate_id.qualified_name!r}"
                ),
                path=path,
            )
        )
        return
    if predicate_id not in available:
        issues.append(
            RealtimeProgramIssue(
                code="realtime_predicate_slot_unavailable",
                message=(
                    f"predicate acquisition slot {predicate_id.qualified_name!r} "
                    "is not available before the conditional"
                ),
                path=path,
            )
        )
    if slot.contract.acquisition_kind is not AcquisitionKind.CLASSIFIED_STATE:
        issues.append(
            RealtimeProgramIssue(
                code="realtime_predicate_not_classified",
                message=(
                    f"predicate acquisition slot {predicate_id.qualified_name!r} "
                    "must produce a classified state"
                ),
                path=path,
            )
        )
    required_dimensions = frozenset(
        dimension.id for dimension in slot.contract.dimensions
    )
    if not required_dimensions <= active_result_dimensions:
        issues.append(
            RealtimeProgramIssue(
                code="realtime_predicate_dimensions_inactive",
                message=(
                    f"predicate acquisition slot {predicate_id.qualified_name!r} "
                    f"has local dimensions {tuple(sorted(required_dimensions))!r} "
                    "that are not covered by the active real-time repeats"
                ),
                path=path,
            )
        )
    acquisition_dimensions = available.get(predicate_id, frozenset())
    if not required_dimensions <= acquisition_dimensions:
        issues.append(
            RealtimeProgramIssue(
                code="realtime_predicate_not_current_iteration",
                message=(
                    f"predicate acquisition slot {predicate_id.qualified_name!r} "
                    "was not acquired in the current iterations of its local "
                    "dimensions"
                ),
                path=path,
            )
        )


def _validate_dataflow(
    instruction: RealtimeInstruction,
    *,
    path: tuple[RealtimePathItem, ...],
    available: dict[AcquisitionSlotId, frozenset[str]],
    active_result_dimensions: frozenset[str],
    slot_index: dict[AcquisitionSlotId, AcquisitionSlot],
    issues: list[RealtimeProgramIssue],
    inside_conditional_branch: bool,
) -> dict[AcquisitionSlotId, frozenset[str]]:
    if isinstance(instruction, RealtimeNoOp):
        return available
    if isinstance(instruction, ScheduledBlock):
        if inside_conditional_branch and instruction.program.acquisition_slots:
            issues.append(
                RealtimeProgramIssue(
                    code="realtime_branch_acquisition",
                    message=(
                        "conditional branches cannot contain acquisitions; "
                        "place measurement before or after the conditional"
                    ),
                    path=path,
                )
            )
        return {
            **available,
            **{
                slot.id: active_result_dimensions
                for slot in instruction.program.acquisition_slots
            },
        }
    if isinstance(instruction, RealtimeSequence):
        selected = available
        for index, child in enumerate(instruction.instructions):
            selected = _validate_dataflow(
                child,
                path=(*path, "sequence", index),
                available=selected,
                active_result_dimensions=active_result_dimensions,
                slot_index=slot_index,
                issues=issues,
                inside_conditional_branch=inside_conditional_branch,
            )
        return selected
    if isinstance(instruction, RealtimeRepeat):
        profile = _profile(instruction.instruction, path=(*path, "repeat"))
        nested_dimensions = _validate_repeat_shape(
            instruction,
            profile,
            path=path,
            active_result_dimensions=active_result_dimensions,
            issues=issues,
        )
        return _validate_dataflow(
            instruction.instruction,
            path=(*path, "repeat"),
            available=available,
            active_result_dimensions=nested_dimensions,
            slot_index=slot_index,
            issues=issues,
            inside_conditional_branch=inside_conditional_branch,
        )

    _validate_predicate(
        instruction.predicate,
        path=(*path, "predicate"),
        available=available,
        active_result_dimensions=active_result_dimensions,
        slot_index=slot_index,
        issues=issues,
    )
    branch_outputs = tuple(
        _validate_dataflow(
            case.body,
            path=(*path, "cases", case.state),
            available=available,
            active_result_dimensions=active_result_dimensions,
            slot_index=slot_index,
            issues=issues,
            inside_conditional_branch=True,
        )
        for case in instruction.cases
    )
    default_output = _validate_dataflow(
        instruction.default,
        path=(*path, "default"),
        available=available,
        active_result_dimensions=active_result_dimensions,
        slot_index=slot_index,
        issues=issues,
        inside_conditional_branch=True,
    )
    outputs = (*branch_outputs, default_output)
    common_slots = set(available)
    for output in outputs:
        common_slots.intersection_update(output)
    selected: dict[AcquisitionSlotId, frozenset[str]] = {}
    for slot_id in common_slots:
        dimensions = available[slot_id]
        for output in outputs:
            dimensions = dimensions & output[slot_id]
        selected[slot_id] = dimensions
    return selected


__all__ = [
    "ClassifiedStatePredicate",
    "RealtimeCase",
    "RealtimeConditional",
    "RealtimeEvent",
    "RealtimeInstruction",
    "RealtimeNoOp",
    "RealtimeProgramIssue",
    "RealtimeProgramValidationError",
    "RealtimeRepeat",
    "RealtimeSequence",
    "ScheduledBlock",
    "TargetProgram",
    "TargetProgramEnvelope",
]

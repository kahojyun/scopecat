"""Hardware-independent pulse authoring and canonical scheduling.

The authoring tree in :class:`PulseProgram` describes relative composition.  Target
compilers deliberately consume :class:`ScheduledPulseProgram` instead: scheduling
flattens composition, normalizes quantities, validates acquisition closure, and
proves that each logical signal has a non-overlapping timeline.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import TypeGuard, cast

from scopecat import Quantity

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CouplerId,
    PulseEventId,
    PulseProgramId,
    QubitId,
)
from scopecat_quantum.acquisitions import AcquisitionKind


@dataclass(frozen=True, slots=True)
class DriveSignal:
    """Logical microwave-drive signal for a qubit."""

    qubit: QubitId


@dataclass(frozen=True, slots=True)
class ReadoutSignal:
    """Logical readout-stimulus signal for a qubit."""

    qubit: QubitId


@dataclass(frozen=True, slots=True)
class AcquireSignal:
    """Logical acquisition signal for a qubit."""

    qubit: QubitId


@dataclass(frozen=True, slots=True)
class FluxSignal:
    """Logical flux-control signal for either a qubit or a coupler."""

    owner: QubitId | CouplerId


type LogicalSignal = DriveSignal | ReadoutSignal | AcquireSignal | FluxSignal
type PlaySignal = DriveSignal | ReadoutSignal | FluxSignal
type FrameSignal = DriveSignal | ReadoutSignal


def _zero_phase() -> Quantity:
    return Quantity(value=0.0, unit="rad")


@dataclass(frozen=True, slots=True)
class Constant:
    """A constant complex envelope over a finite duration."""

    duration: Quantity
    amplitude: Quantity
    phase: Quantity = field(default_factory=_zero_phase)


@dataclass(frozen=True, slots=True)
class Gaussian:
    """A duration-truncated Gaussian envelope."""

    duration: Quantity
    amplitude: Quantity
    sigma: Quantity
    phase: Quantity = field(default_factory=_zero_phase)


@dataclass(frozen=True, slots=True)
class DRAG:
    """A Gaussian envelope with a derivative quadrature correction.

    ``beta`` has units of time, so multiplying it by the Gaussian derivative has
    the same amplitude dimension as the in-phase component.
    """

    duration: Quantity
    amplitude: Quantity
    sigma: Quantity
    beta: Quantity
    phase: Quantity = field(default_factory=_zero_phase)


type AnalyticEnvelope = Constant | Gaussian | DRAG


@dataclass(frozen=True, slots=True)
class AcquisitionSlot:
    """A declared result slot that an ``Acquire`` instruction must close once."""

    id: AcquisitionSlotId
    kind: AcquisitionKind
    signal: AcquireSignal


@dataclass(frozen=True, slots=True)
class Play:
    """Play an analytic envelope on a non-acquisition logical signal."""

    id: PulseEventId
    signal: PlaySignal
    envelope: AnalyticEnvelope


@dataclass(frozen=True, slots=True)
class Acquire:
    """Acquire one declared result slot."""

    id: PulseEventId
    signal: AcquireSignal
    slot_id: AcquisitionSlotId
    duration: Quantity


@dataclass(frozen=True, slots=True)
class Delay:
    """Reserve time on one logical signal without playing a waveform."""

    id: PulseEventId
    signal: LogicalSignal
    duration: Quantity


@dataclass(frozen=True, slots=True)
class ShiftPhase:
    """Advance one oscillator-backed logical signal's phase frame.

    This is a relative, zero-duration frame operation.  Keeping the phase
    change explicit lets target compilers preserve virtual-Z and readout-frame
    semantics without baking mutable frame state into analytic envelopes.
    """

    id: PulseEventId
    signal: FrameSignal
    phase: Quantity


@dataclass(frozen=True, slots=True)
class Barrier:
    """A zero-duration synchronization marker over logical signals."""

    id: PulseEventId
    signals: tuple[LogicalSignal, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "signals", tuple(self.signals))


@dataclass(frozen=True, slots=True)
class Sequence:
    """Compose instructions consecutively on a shared program timeline."""

    instructions: tuple[PulseInstruction, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "instructions", tuple(self.instructions))


@dataclass(frozen=True, slots=True)
class Parallel:
    """Compose instruction branches from the same start time."""

    branches: tuple[PulseInstruction, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "branches", tuple(self.branches))


type PulseLeaf = Play | Acquire | Delay | ShiftPhase | Barrier
type PulseInstruction = PulseLeaf | Sequence | Parallel


def iter_pulse_leaves(instruction: PulseInstruction) -> Iterator[PulseLeaf]:
    """Yield pulse leaves in deterministic structural order."""

    raw_instruction = cast("object", instruction)
    if isinstance(raw_instruction, Play | Acquire | Delay | ShiftPhase | Barrier):
        yield raw_instruction
        return
    if isinstance(raw_instruction, Sequence):
        children = raw_instruction.instructions
    elif isinstance(raw_instruction, Parallel):
        children = raw_instruction.branches
    else:
        msg = "pulse tree contains an unsupported instruction node"
        raise TypeError(msg)
    for child in children:
        yield from iter_pulse_leaves(child)


@dataclass(frozen=True, slots=True)
class PulseProgram:
    """Relative pulse authoring IR; never a target-compiler input."""

    id: PulseProgramId
    body: PulseInstruction
    acquisition_slots: tuple[AcquisitionSlot, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "acquisition_slots", tuple(self.acquisition_slots))


@dataclass(frozen=True, slots=True)
class ScheduledPulseEvent:
    """One normalized leaf at an absolute start time in seconds."""

    id: PulseEventId
    start_seconds: Decimal
    duration_seconds: Decimal
    instruction: PulseLeaf


@dataclass(frozen=True, slots=True, init=False)
class ScheduledPulseProgram:
    """Canonical, validated pulse IR accepted by target compilers.

    :func:`schedule` establishes the pulse invariants before constructing this
    trusted, immutable internal-stage value.
    """

    id: PulseProgramId
    duration_seconds: Decimal
    events: tuple[ScheduledPulseEvent, ...]
    acquisition_slots: tuple[AcquisitionSlot, ...] = ()

    def __init__(
        self,
        id: PulseProgramId,  # noqa: A002
        duration_seconds: Decimal,
        events: tuple[ScheduledPulseEvent, ...],
        acquisition_slots: tuple[AcquisitionSlot, ...] = (),
    ) -> None:
        object.__setattr__(self, "id", id)
        object.__setattr__(self, "duration_seconds", duration_seconds)
        object.__setattr__(self, "events", tuple(events))
        object.__setattr__(self, "acquisition_slots", tuple(acquisition_slots))


@dataclass(frozen=True, slots=True)
class PulseIssue:
    """One structured pulse validation failure."""

    code: str
    message: str
    instruction_id: PulseEventId | None = None
    path: tuple[int, ...] = ()


class PulseValidationError(ValueError):
    """Aggregate of all independently discoverable pulse issues."""

    __slots__ = ("issues",)

    def __init__(self, issues: tuple[PulseIssue, ...]) -> None:
        if not issues:
            msg = "pulse validation errors require at least one issue"
            raise ValueError(msg)
        self.issues = tuple(issues)
        summary = "; ".join(f"{issue.code}: {issue.message}" for issue in self.issues)
        super().__init__(summary)


@dataclass(frozen=True, slots=True)
class _PlacedLeaf:
    leaf: PulseLeaf
    start: Decimal
    duration: Decimal
    path: tuple[int, ...]
    sequence_predecessors: frozenset[PulseEventId] = frozenset()


_TIME_FACTORS: dict[str, Decimal] = {
    "s": Decimal(1),
    "ms": Decimal("1e-3"),
    "us": Decimal("1e-6"),
    "ns": Decimal("1e-9"),
}

_MISSING = object()


def _runtime_object(value: object) -> object:
    """Erase a static authoring-IR type before checking its runtime shape."""

    return value


def _runtime_field(value: object, name: str) -> object:
    """Read a field without allowing malformed runtime objects to leak errors."""

    return getattr(value, name, _MISSING)


def _runtime_tuple(value: object) -> tuple[object, ...] | None:
    return cast("tuple[object, ...]", value) if isinstance(value, tuple) else None


def _has_valid_nominal_value(value: object) -> bool:
    raw_value = _runtime_field(value, "value")
    return isinstance(raw_value, str) and bool(raw_value.strip())


def _has_valid_structural_identity(
    value: object,
) -> TypeGuard[PulseEventId | AcquisitionSlotId]:
    if not isinstance(value, PulseEventId | AcquisitionSlotId):
        return False
    local_id = _runtime_field(value, "local_id")
    scope = _runtime_tuple(_runtime_field(value, "scope"))
    structurally_valid = (
        isinstance(local_id, str)
        and bool(local_id.strip())
        and scope is not None
        and all(isinstance(segment, str) and bool(segment.strip()) for segment in scope)
    )
    if not structurally_valid:
        return False
    try:
        _ = value.qualified_name
    except UnicodeEncodeError:
        return False
    return True


def _has_valid_pulse_event_identity(value: object) -> TypeGuard[PulseEventId]:
    return isinstance(value, PulseEventId) and _has_valid_structural_identity(value)


def _has_valid_acquisition_slot_identity(
    value: object,
) -> TypeGuard[AcquisitionSlotId]:
    return isinstance(value, AcquisitionSlotId) and _has_valid_structural_identity(
        value
    )


def _structural_identity_sort_key(
    value: PulseEventId | AcquisitionSlotId,
) -> tuple[tuple[str, ...], str]:
    return (value.scope, value.local_id)


def _is_quantity(value: object) -> TypeGuard[Quantity]:
    if not isinstance(value, Quantity):
        return False
    raw_value = _runtime_field(value, "value")
    raw_unit = _runtime_field(value, "unit")
    return (
        isinstance(raw_value, int | float)
        and not isinstance(raw_value, bool)
        and isinstance(raw_unit, str)
    )


def _is_finite_number(value: float) -> bool:
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _issue(
    issues: list[PulseIssue],
    code: str,
    message: str,
    *,
    instruction_id: PulseEventId | None = None,
    path: tuple[int, ...] = (),
) -> None:
    issues.append(
        PulseIssue(
            code=code,
            message=message,
            instruction_id=instruction_id,
            path=path,
        )
    )


def _time_value(
    quantity: Quantity,
    *,
    name: str,
    issues: list[PulseIssue],
    instruction_id: PulseEventId,
    path: tuple[int, ...],
    positive: bool,
) -> Decimal | None:
    factor = _TIME_FACTORS.get(quantity.unit)
    if factor is None:
        _issue(
            issues,
            "pulse_time_unit_invalid",
            f"{name} must have a time unit, got {quantity.unit!r}",
            instruction_id=instruction_id,
            path=path,
        )
        return None
    if not _is_finite_number(quantity.value):
        _issue(
            issues,
            "pulse_quantity_nonfinite",
            f"{name} must be finite",
            instruction_id=instruction_id,
            path=path,
        )
        return None
    result = Decimal(str(quantity.value)) * factor
    if positive and result <= 0:
        _issue(
            issues,
            "pulse_duration_nonpositive",
            f"{name} must be positive",
            instruction_id=instruction_id,
            path=path,
        )
        return None
    return result


def _representable_quantity_seconds(
    value: Decimal,
    *,
    name: str,
    issues: list[PulseIssue],
    instruction_id: PulseEventId,
    path: tuple[int, ...],
) -> float | None:
    try:
        converted = float(value)
    except OverflowError:
        converted = math.inf if value >= 0 else -math.inf
    if not math.isfinite(converted):
        _issue(
            issues,
            "pulse_quantity_unrepresentable",
            f"{name} cannot be represented as a finite Quantity in seconds",
            instruction_id=instruction_id,
            path=path,
        )
        return None
    if value != 0 and converted == 0:
        _issue(
            issues,
            "pulse_quantity_unrepresentable",
            f"nonzero {name} rounds to zero in a Quantity expressed in seconds",
            instruction_id=instruction_id,
            path=path,
        )
        return None
    return converted


def _normalized_amplitude(
    quantity: Quantity,
    *,
    issues: list[PulseIssue],
    instruction_id: PulseEventId,
    path: tuple[int, ...],
) -> Quantity | None:
    if not _is_finite_number(quantity.value):
        _issue(
            issues,
            "pulse_quantity_nonfinite",
            "amplitude must be finite",
            instruction_id=instruction_id,
            path=path,
        )
        return None
    for unit in ("arb", "ratio", "V"):
        try:
            return quantity.to(unit)
        except ValueError:
            pass
    _issue(
        issues,
        "pulse_amplitude_unit_invalid",
        (
            "amplitude must be dimensionless, arbitrary, or voltage, "
            f"got {quantity.unit!r}"
        ),
        instruction_id=instruction_id,
        path=path,
    )
    return None


def _normalized_phase(
    quantity: Quantity,
    *,
    issues: list[PulseIssue],
    instruction_id: PulseEventId,
    path: tuple[int, ...],
) -> Quantity | None:
    if not _is_finite_number(quantity.value):
        _issue(
            issues,
            "pulse_quantity_nonfinite",
            "phase must be finite",
            instruction_id=instruction_id,
            path=path,
        )
        return None
    try:
        return quantity.to("rad")
    except ValueError:
        _issue(
            issues,
            "pulse_phase_unit_invalid",
            f"phase must have a phase unit, got {quantity.unit!r}",
            instruction_id=instruction_id,
            path=path,
        )
        return None


def _normalized_envelope(
    envelope: AnalyticEnvelope,
    *,
    issues: list[PulseIssue],
    instruction_id: PulseEventId,
    path: tuple[int, ...],
) -> tuple[AnalyticEnvelope, Decimal] | None:
    duration = _time_value(
        envelope.duration,
        name="envelope duration",
        issues=issues,
        instruction_id=instruction_id,
        path=path,
        positive=True,
    )
    amplitude = _normalized_amplitude(
        envelope.amplitude,
        issues=issues,
        instruction_id=instruction_id,
        path=path,
    )
    phase = _normalized_phase(
        envelope.phase,
        issues=issues,
        instruction_id=instruction_id,
        path=path,
    )
    sigma: Decimal | None = None
    beta: Decimal | None = None
    if isinstance(envelope, Gaussian | DRAG):
        sigma = _time_value(
            envelope.sigma,
            name="Gaussian sigma",
            issues=issues,
            instruction_id=instruction_id,
            path=path,
            positive=True,
        )
        if duration is not None and sigma is not None and sigma > duration:
            _issue(
                issues,
                "pulse_sigma_exceeds_duration",
                "Gaussian sigma cannot exceed the envelope duration",
                instruction_id=instruction_id,
                path=path,
            )
    if isinstance(envelope, DRAG):
        beta = _time_value(
            envelope.beta,
            name="DRAG beta",
            issues=issues,
            instruction_id=instruction_id,
            path=path,
            positive=False,
        )
    if duration is None or amplitude is None or phase is None:
        return None
    normalized_duration_value = _representable_quantity_seconds(
        duration,
        name="envelope duration",
        issues=issues,
        instruction_id=instruction_id,
        path=path,
    )
    if normalized_duration_value is None:
        return None
    normalized_duration = Quantity(value=normalized_duration_value, unit="s")
    if isinstance(envelope, Constant):
        return replace(
            envelope,
            duration=normalized_duration,
            amplitude=amplitude,
            phase=phase,
        ), duration
    if sigma is None:
        return None
    normalized_sigma_value = _representable_quantity_seconds(
        sigma,
        name="Gaussian sigma",
        issues=issues,
        instruction_id=instruction_id,
        path=path,
    )
    if normalized_sigma_value is None:
        return None
    normalized_sigma = Quantity(value=normalized_sigma_value, unit="s")
    if isinstance(envelope, Gaussian):
        return replace(
            envelope,
            duration=normalized_duration,
            amplitude=amplitude,
            sigma=normalized_sigma,
            phase=phase,
        ), duration
    if beta is None:
        return None
    normalized_beta_value = _representable_quantity_seconds(
        beta,
        name="DRAG beta",
        issues=issues,
        instruction_id=instruction_id,
        path=path,
    )
    if normalized_beta_value is None:
        return None
    return replace(
        envelope,
        duration=normalized_duration,
        amplitude=amplitude,
        sigma=normalized_sigma,
        beta=Quantity(value=normalized_beta_value, unit="s"),
        phase=phase,
    ), duration


def _is_logical_signal(value: object) -> TypeGuard[LogicalSignal]:
    if isinstance(value, DriveSignal | ReadoutSignal | AcquireSignal):
        owner = _runtime_field(value, "qubit")
        return isinstance(owner, QubitId) and _has_valid_nominal_value(owner)
    if isinstance(value, FluxSignal):
        owner = _runtime_field(value, "owner")
        return isinstance(owner, QubitId | CouplerId) and _has_valid_nominal_value(
            owner
        )
    return False


def _is_play_signal(value: object) -> TypeGuard[PlaySignal]:
    return isinstance(value, DriveSignal | ReadoutSignal | FluxSignal) and (
        _is_logical_signal(value)
    )


def _is_frame_signal(value: object) -> TypeGuard[FrameSignal]:
    return isinstance(value, DriveSignal | ReadoutSignal) and _is_logical_signal(value)


def _is_acquire_signal(value: object) -> TypeGuard[AcquireSignal]:
    return isinstance(value, AcquireSignal) and _is_logical_signal(value)


def _is_acquisition_kind(value: object) -> TypeGuard[AcquisitionKind]:
    return isinstance(value, AcquisitionKind)


def _is_analytic_envelope(value: object) -> TypeGuard[AnalyticEnvelope]:
    return isinstance(value, Constant | Gaussian | DRAG)


def _validate_quantity_structure(
    value: object,
    *,
    name: str,
    issues: list[PulseIssue],
    instruction_id: PulseEventId | None = None,
    path: tuple[int, ...] = (),
) -> bool:
    if not _is_quantity(value):
        _issue(
            issues,
            "pulse_quantity_invalid",
            f"{name} must be a Quantity with numeric value and string unit",
            instruction_id=instruction_id,
            path=path,
        )
        return False
    return True


def _validate_envelope_structure(
    envelope: object,
    *,
    issues: list[PulseIssue],
    instruction_id: PulseEventId | None,
    path: tuple[int, ...],
) -> bool:
    if not _is_analytic_envelope(envelope):
        _issue(
            issues,
            "pulse_envelope_invalid",
            "Play requires a supported analytic envelope",
            instruction_id=instruction_id,
            path=path,
        )
        return True
    valid = _validate_quantity_structure(
        _runtime_field(envelope, "duration"),
        name="envelope duration",
        issues=issues,
        instruction_id=instruction_id,
        path=path,
    )
    valid = (
        _validate_quantity_structure(
            _runtime_field(envelope, "amplitude"),
            name="envelope amplitude",
            issues=issues,
            instruction_id=instruction_id,
            path=path,
        )
        and valid
    )
    valid = (
        _validate_quantity_structure(
            _runtime_field(envelope, "phase"),
            name="envelope phase",
            issues=issues,
            instruction_id=instruction_id,
            path=path,
        )
        and valid
    )
    if isinstance(envelope, Gaussian | DRAG):
        valid = (
            _validate_quantity_structure(
                _runtime_field(envelope, "sigma"),
                name="Gaussian sigma",
                issues=issues,
                instruction_id=instruction_id,
                path=path,
            )
            and valid
        )
    if isinstance(envelope, DRAG):
        valid = (
            _validate_quantity_structure(
                _runtime_field(envelope, "beta"),
                name="DRAG beta",
                issues=issues,
                instruction_id=instruction_id,
                path=path,
            )
            and valid
        )
    return valid


def _validate_instruction_id(
    instruction: PulseLeaf,
    *,
    issues: list[PulseIssue],
    path: tuple[int, ...],
) -> PulseEventId | None:
    raw_id = _runtime_field(instruction, "id")
    if _has_valid_pulse_event_identity(raw_id):
        assert isinstance(raw_id, PulseEventId)
        return raw_id
    _issue(
        issues,
        "pulse_instruction_id_invalid",
        "pulse leaf id must be a PulseEventId",
        path=path,
    )
    return None


def _validate_instruction_structure(
    instruction: object,
    *,
    issues: list[PulseIssue],
    path: tuple[int, ...],
) -> bool:
    if isinstance(instruction, Sequence):
        children = _runtime_tuple(_runtime_field(instruction, "instructions"))
        if children is None:
            _issue(
                issues,
                "pulse_sequence_instructions_invalid",
                "Sequence instructions must be a tuple",
                path=path,
            )
            return False
        valid = True
        for index, child in enumerate(children):
            valid = (
                _validate_instruction_structure(
                    child,
                    issues=issues,
                    path=(*path, index),
                )
                and valid
            )
        return valid
    if isinstance(instruction, Parallel):
        branches = _runtime_tuple(_runtime_field(instruction, "branches"))
        if branches is None:
            _issue(
                issues,
                "pulse_parallel_branches_invalid",
                "Parallel branches must be a tuple",
                path=path,
            )
            return False
        valid = True
        for index, branch in enumerate(branches):
            valid = (
                _validate_instruction_structure(
                    branch,
                    issues=issues,
                    path=(*path, index),
                )
                and valid
            )
        return valid
    if not isinstance(instruction, Play | Acquire | Delay | ShiftPhase | Barrier):
        _issue(
            issues,
            "pulse_instruction_invalid",
            (
                "pulse nodes must be Play, Acquire, Delay, ShiftPhase, Barrier, "
                "Sequence, or Parallel"
            ),
            path=path,
        )
        return False

    instruction_id = _validate_instruction_id(
        instruction,
        issues=issues,
        path=path,
    )
    valid = instruction_id is not None
    if isinstance(instruction, Play):
        if not _is_play_signal(_runtime_field(instruction, "signal")):
            _issue(
                issues,
                "pulse_signal_instruction_invalid",
                "Play requires a drive, readout, or flux signal",
                instruction_id=instruction_id,
                path=path,
            )
        valid = (
            _validate_envelope_structure(
                _runtime_field(instruction, "envelope"),
                issues=issues,
                instruction_id=instruction_id,
                path=path,
            )
            and valid
        )
        return valid
    if isinstance(instruction, Acquire):
        if not _is_acquire_signal(_runtime_field(instruction, "signal")):
            _issue(
                issues,
                "pulse_signal_instruction_invalid",
                "Acquire requires an acquisition signal",
                instruction_id=instruction_id,
                path=path,
            )
        slot_id = _runtime_field(instruction, "slot_id")
        if not _has_valid_acquisition_slot_identity(slot_id):
            _issue(
                issues,
                "pulse_acquisition_slot_id_invalid",
                "Acquire slot_id must be an AcquisitionSlotId",
                instruction_id=instruction_id,
                path=path,
            )
            valid = False
        valid = (
            _validate_quantity_structure(
                _runtime_field(instruction, "duration"),
                name="acquisition duration",
                issues=issues,
                instruction_id=instruction_id,
                path=path,
            )
            and valid
        )
        return valid
    if isinstance(instruction, Delay):
        if not _is_logical_signal(_runtime_field(instruction, "signal")):
            _issue(
                issues,
                "pulse_signal_instruction_invalid",
                "Delay requires one logical signal",
                instruction_id=instruction_id,
                path=path,
            )
        valid = (
            _validate_quantity_structure(
                _runtime_field(instruction, "duration"),
                name="delay duration",
                issues=issues,
                instruction_id=instruction_id,
                path=path,
            )
            and valid
        )
        return valid
    if isinstance(instruction, ShiftPhase):
        if not _is_frame_signal(_runtime_field(instruction, "signal")):
            _issue(
                issues,
                "pulse_signal_instruction_invalid",
                "ShiftPhase requires a drive or readout signal",
                instruction_id=instruction_id,
                path=path,
            )
        valid = (
            _validate_quantity_structure(
                _runtime_field(instruction, "phase"),
                name="phase shift",
                issues=issues,
                instruction_id=instruction_id,
                path=path,
            )
            and valid
        )
        return valid

    signals = _runtime_tuple(_runtime_field(instruction, "signals"))
    if signals is None:
        _issue(
            issues,
            "pulse_barrier_signals_invalid",
            "Barrier signals must be a tuple",
            instruction_id=instruction_id,
            path=path,
        )
        return False
    if not all(_is_logical_signal(signal) for signal in signals):
        _issue(
            issues,
            "pulse_signal_instruction_invalid",
            "Barrier contains a non-logical signal",
            instruction_id=instruction_id,
            path=path,
        )
    return valid


def _validate_acquisition_declarations_structure(
    slots: object,
    *,
    issues: list[PulseIssue],
) -> bool:
    slot_values = _runtime_tuple(slots)
    if slot_values is None:
        _issue(
            issues,
            "pulse_acquisition_slots_invalid",
            "PulseProgram acquisition_slots must be a tuple",
        )
        return False
    valid = True
    for index, slot in enumerate(slot_values):
        path = (index,)
        if not isinstance(slot, AcquisitionSlot):
            _issue(
                issues,
                "pulse_acquisition_slot_invalid",
                f"acquisition_slots[{index}] must be an AcquisitionSlot",
                path=path,
            )
            valid = False
            continue
        slot_id = _runtime_field(slot, "id")
        if not _has_valid_acquisition_slot_identity(slot_id):
            _issue(
                issues,
                "pulse_acquisition_slot_id_invalid",
                f"acquisition_slots[{index}].id must be an AcquisitionSlotId",
                path=path,
            )
            valid = False
        raw_kind = _runtime_field(slot, "kind")
        if not isinstance(raw_kind, AcquisitionKind):
            message = (
                f"acquisition slot {slot_id.value!r} has an invalid kind"
                if _has_valid_acquisition_slot_identity(slot_id)
                else f"acquisition_slots[{index}].kind must be an AcquisitionKind"
            )
            _issue(
                issues,
                "pulse_acquisition_kind_invalid",
                message,
                path=() if _has_valid_acquisition_slot_identity(slot_id) else path,
            )
        raw_signal = _runtime_field(slot, "signal")
        if not _is_acquire_signal(raw_signal):
            message = (
                f"acquisition slot {slot_id.value!r} requires an acquisition signal"
                if _has_valid_acquisition_slot_identity(slot_id)
                else (
                    f"acquisition_slots[{index}].signal must be an AcquireSignal "
                    "with nominal qubit owner"
                )
            )
            _issue(
                issues,
                "pulse_acquisition_signal_invalid",
                message,
                path=() if _has_valid_acquisition_slot_identity(slot_id) else path,
            )
    return valid


def _validate_program_structure(
    program: object,
    issues: list[PulseIssue],
) -> tuple[PulseProgram | None, bool]:
    if not isinstance(program, PulseProgram):
        _issue(
            issues,
            "pulse_program_invalid",
            "pulse program must be a PulseProgram",
        )
        return None, False
    program_id = _runtime_field(program, "id")
    if not (
        isinstance(program_id, PulseProgramId) and _has_valid_nominal_value(program_id)
    ):
        _issue(
            issues,
            "pulse_program_id_invalid",
            "pulse program id must be a PulseProgramId",
        )
    body_is_safe = _validate_instruction_structure(
        _runtime_field(program, "body"),
        issues=issues,
        path=(),
    )
    declarations_are_safe = _validate_acquisition_declarations_structure(
        _runtime_field(program, "acquisition_slots"),
        issues=issues,
    )
    return program, body_is_safe and declarations_are_safe


def _signal_key(signal: LogicalSignal) -> tuple[str, str, str]:
    if isinstance(signal, DriveSignal):
        return ("drive", "qubit", signal.qubit.value)
    if isinstance(signal, ReadoutSignal):
        return ("readout", "qubit", signal.qubit.value)
    if isinstance(signal, AcquireSignal):
        return ("acquire", "qubit", signal.qubit.value)
    owner_kind = "qubit" if isinstance(signal.owner, QubitId) else "coupler"
    return ("flux", owner_kind, signal.owner.value)


def _leaf_signals(leaf: PulseLeaf) -> tuple[LogicalSignal, ...]:
    if isinstance(leaf, Barrier):
        return leaf.signals
    return (leaf.signal,)


def _place_instruction(
    instruction: PulseInstruction,
    *,
    start: Decimal,
    path: tuple[int, ...],
    issues: list[PulseIssue],
    seen_ids: set[PulseEventId],
    acquisition_uses: dict[AcquisitionSlotId, list[Acquire]],
) -> tuple[list[_PlacedLeaf], Decimal]:
    if isinstance(instruction, Sequence):
        placed: list[_PlacedLeaf] = []
        cursor = start
        preceding_ids: set[PulseEventId] = set()
        for index, child in enumerate(instruction.instructions):
            child_events, child_duration = _place_instruction(
                child,
                start=cursor,
                path=(*path, index),
                issues=issues,
                seen_ids=seen_ids,
                acquisition_uses=acquisition_uses,
            )
            if preceding_ids:
                child_events = [
                    replace(
                        event,
                        sequence_predecessors=(
                            event.sequence_predecessors | preceding_ids
                        ),
                    )
                    for event in child_events
                ]
            placed.extend(child_events)
            preceding_ids.update(event.leaf.id for event in child_events)
            cursor += child_duration
        return placed, cursor - start
    if isinstance(instruction, Parallel):
        placed = []
        duration = Decimal(0)
        for index, child in enumerate(instruction.branches):
            child_events, child_duration = _place_instruction(
                child,
                start=start,
                path=(*path, index),
                issues=issues,
                seen_ids=seen_ids,
                acquisition_uses=acquisition_uses,
            )
            placed.extend(child_events)
            duration = max(duration, child_duration)
        return placed, duration

    event_id = instruction.id
    if event_id in seen_ids:
        _issue(
            issues,
            "pulse_instruction_duplicate",
            f"instruction id {event_id.value!r} is declared more than once",
            instruction_id=event_id,
            path=path,
        )
    else:
        seen_ids.add(event_id)

    normalized: PulseLeaf = instruction
    duration = Decimal(0)
    if isinstance(instruction, Play):
        if not _is_play_signal(instruction.signal):
            _issue(
                issues,
                "pulse_signal_instruction_invalid",
                "Play requires a drive, readout, or flux signal",
                instruction_id=event_id,
                path=path,
            )
        envelope = None
        if _is_analytic_envelope(instruction.envelope):
            envelope = _normalized_envelope(
                instruction.envelope,
                issues=issues,
                instruction_id=event_id,
                path=path,
            )
        else:
            _issue(
                issues,
                "pulse_envelope_invalid",
                "Play requires a supported analytic envelope",
                instruction_id=event_id,
                path=path,
            )
        if envelope is not None:
            normalized_envelope, duration = envelope
            normalized = replace(instruction, envelope=normalized_envelope)
    elif isinstance(instruction, Acquire):
        if not _is_acquire_signal(instruction.signal):
            _issue(
                issues,
                "pulse_signal_instruction_invalid",
                "Acquire requires an acquisition signal",
                instruction_id=event_id,
                path=path,
            )
        acquisition_uses.setdefault(instruction.slot_id, []).append(instruction)
        normalized_duration = _time_value(
            instruction.duration,
            name="acquisition duration",
            issues=issues,
            instruction_id=event_id,
            path=path,
            positive=True,
        )
        if normalized_duration is not None:
            duration = normalized_duration
            normalized_duration_value = _representable_quantity_seconds(
                duration,
                name="acquisition duration",
                issues=issues,
                instruction_id=event_id,
                path=path,
            )
            if normalized_duration_value is not None:
                normalized = replace(
                    instruction,
                    duration=Quantity(value=normalized_duration_value, unit="s"),
                )
    elif isinstance(instruction, Delay):
        if not _is_logical_signal(instruction.signal):
            _issue(
                issues,
                "pulse_signal_instruction_invalid",
                "Delay requires one logical signal",
                instruction_id=event_id,
                path=path,
            )
        normalized_duration = _time_value(
            instruction.duration,
            name="delay duration",
            issues=issues,
            instruction_id=event_id,
            path=path,
            positive=True,
        )
        if normalized_duration is not None:
            duration = normalized_duration
            normalized_duration_value = _representable_quantity_seconds(
                duration,
                name="delay duration",
                issues=issues,
                instruction_id=event_id,
                path=path,
            )
            if normalized_duration_value is not None:
                normalized = replace(
                    instruction,
                    duration=Quantity(value=normalized_duration_value, unit="s"),
                )
    elif isinstance(instruction, ShiftPhase):
        if not _is_frame_signal(instruction.signal):
            _issue(
                issues,
                "pulse_signal_instruction_invalid",
                "ShiftPhase requires a drive or readout signal",
                instruction_id=event_id,
                path=path,
            )
        normalized_phase = _normalized_phase(
            instruction.phase,
            issues=issues,
            instruction_id=event_id,
            path=path,
        )
        if normalized_phase is not None:
            normalized = replace(instruction, phase=normalized_phase)
    else:
        invalid_signals = [
            signal for signal in instruction.signals if not _is_logical_signal(signal)
        ]
        if invalid_signals:
            _issue(
                issues,
                "pulse_signal_instruction_invalid",
                "Barrier contains a non-logical signal",
                instruction_id=event_id,
                path=path,
            )
        if not invalid_signals and len(set(instruction.signals)) != len(
            instruction.signals
        ):
            _issue(
                issues,
                "pulse_barrier_signal_duplicate",
                "Barrier signals must be unique",
                instruction_id=event_id,
                path=path,
            )
        if not invalid_signals:
            normalized = replace(
                instruction,
                signals=tuple(sorted(instruction.signals, key=_signal_key)),
            )
    return [_PlacedLeaf(normalized, start, duration, path)], duration


def _validate_acquisitions(
    slots: tuple[AcquisitionSlot, ...],
    uses: dict[AcquisitionSlotId, list[Acquire]],
    issues: list[PulseIssue],
) -> tuple[AcquisitionSlot, ...]:
    declarations: dict[AcquisitionSlotId, AcquisitionSlot] = {}
    for slot in slots:
        if slot.id in declarations:
            _issue(
                issues,
                "pulse_acquisition_slot_duplicate",
                f"acquisition slot {slot.id.value!r} is declared more than once",
            )
        else:
            declarations[slot.id] = slot
        if not _is_acquisition_kind(slot.kind):
            _issue(
                issues,
                "pulse_acquisition_kind_invalid",
                f"acquisition slot {slot.id.value!r} has an invalid kind",
            )
        if not _is_acquire_signal(slot.signal):
            _issue(
                issues,
                "pulse_acquisition_signal_invalid",
                f"acquisition slot {slot.id.value!r} requires an acquisition signal",
            )

    for slot_id, instructions in uses.items():
        declaration = declarations.get(slot_id)
        if declaration is None:
            for instruction in instructions:
                _issue(
                    issues,
                    "pulse_acquisition_slot_undeclared",
                    f"instruction references undeclared slot {slot_id.value!r}",
                    instruction_id=instruction.id,
                )
            continue
        if len(instructions) > 1:
            _issue(
                issues,
                "pulse_acquisition_slot_multiple",
                f"acquisition slot {slot_id.value!r} is acquired more than once",
            )
        for instruction in instructions:
            if instruction.signal != declaration.signal:
                _issue(
                    issues,
                    "pulse_acquisition_signal_mismatch",
                    f"instruction signal does not match slot {slot_id.value!r}",
                    instruction_id=instruction.id,
                )

    for slot_id in declarations.keys() - uses.keys():
        _issue(
            issues,
            "pulse_acquisition_slot_missing",
            f"declared acquisition slot {slot_id.value!r} is never acquired",
        )
    return tuple(sorted(slots, key=lambda slot: _structural_identity_sort_key(slot.id)))


def _validate_overlaps(placed: list[_PlacedLeaf], issues: list[PulseIssue]) -> None:
    by_signal: dict[LogicalSignal, list[_PlacedLeaf]] = {}
    frame_shifts: list[_PlacedLeaf] = []
    for event in placed:
        if isinstance(event.leaf, ShiftPhase):
            frame_shifts.append(event)
        if event.duration <= 0:
            continue
        for signal in _leaf_signals(event.leaf):
            if _is_logical_signal(signal):
                by_signal.setdefault(signal, []).append(event)
    for signal, events in by_signal.items():
        ordered = sorted(
            events,
            key=lambda event: (
                event.start,
                _structural_identity_sort_key(event.leaf.id),
            ),
        )
        active_end = Decimal(-1)
        active_id: PulseEventId | None = None
        for event in ordered:
            if event.start < active_end:
                assert active_id is not None
                _issue(
                    issues,
                    "pulse_signal_overlap",
                    (
                        f"instructions {active_id.value!r} and "
                        f"{event.leaf.id.value!r} overlap on {_signal_key(signal)!r}"
                    ),
                    instruction_id=event.leaf.id,
                    path=event.path,
                )
            end = event.start + event.duration
            if end > active_end:
                active_end = end
                active_id = event.leaf.id

    for shift in frame_shifts:
        assert isinstance(shift.leaf, ShiftPhase)
        for active in by_signal.get(shift.leaf.signal, ()):
            if (
                isinstance(active.leaf, Play)
                and active.start < shift.start < active.start + active.duration
            ):
                _issue(
                    issues,
                    "pulse_frame_shift_during_play",
                    (
                        f"frame shift {shift.leaf.id.value!r} occurs inside active "
                        f"Play {active.leaf.id.value!r} on "
                        f"{_signal_key(shift.leaf.signal)!r}"
                    ),
                    instruction_id=shift.leaf.id,
                    path=shift.path,
                )


def _event_sort_key(event: _PlacedLeaf) -> tuple[object, ...]:
    signals = tuple(_signal_key(signal) for signal in _leaf_signals(event.leaf))
    instantaneous_priority = 0 if event.duration == 0 else 1
    return (
        event.start,
        instantaneous_priority,
        signals,
        _structural_identity_sort_key(event.leaf.id),
    )


def _ordered_placed_leaves(placed: list[_PlacedLeaf]) -> tuple[_PlacedLeaf, ...]:
    """Return a canonical linearization that retains Sequence causality.

    Positive durations normally make sequence order visible in timestamps.
    Zero-duration frame and barrier operations do not advance the cursor, so
    events at one instant are topologically ordered by their Sequence
    predecessors.  Unrelated Parallel events retain the existing canonical
    signal-and-identity ordering.
    """

    by_start: dict[Decimal, list[_PlacedLeaf]] = {}
    for event in placed:
        by_start.setdefault(event.start, []).append(event)

    ordered: list[_PlacedLeaf] = []
    for start in sorted(by_start):
        remaining = list(by_start[start])
        ids_at_start = {event.leaf.id for event in remaining}
        emitted: set[PulseEventId] = set()
        while remaining:
            ready = [
                event
                for event in remaining
                if not (
                    (event.sequence_predecessors & ids_at_start).difference(emitted)
                )
            ]
            if not ready:
                msg = "pulse sequence precedence unexpectedly contains a cycle"
                raise RuntimeError(msg)
            selected = min(ready, key=_event_sort_key)
            ordered.append(selected)
            emitted.add(selected.leaf.id)
            remaining.remove(selected)
    return tuple(ordered)


def _issue_sort_key(issue: PulseIssue) -> tuple[object, ...]:
    instruction_id = (
        (0, (), "")
        if issue.instruction_id is None
        else (1, *_structural_identity_sort_key(issue.instruction_id))
    )
    return (issue.path, issue.code, instruction_id, issue.message)


def _stable_issues(issues: list[PulseIssue]) -> tuple[PulseIssue, ...]:
    return tuple(sorted(set(issues), key=_issue_sort_key))


def schedule(program: PulseProgram) -> ScheduledPulseProgram:
    """Validate and lower a relative pulse program to canonical scheduled IR.

    All independent failures are returned together in ``PulseValidationError``.
    Exact decimal SI time is retained in the canonical representation, preserving
    sequence reassociation and parallel branch permutation without target-specific
    timeline quantization.
    """

    issues: list[PulseIssue] = []
    validated_program, structurally_safe = _validate_program_structure(
        _runtime_object(program),
        issues,
    )
    if validated_program is None or not structurally_safe:
        raise PulseValidationError(_stable_issues(issues))

    acquisition_uses: dict[AcquisitionSlotId, list[Acquire]] = {}
    placed, duration = _place_instruction(
        validated_program.body,
        start=Decimal(0),
        path=(),
        issues=issues,
        seen_ids=set(),
        acquisition_uses=acquisition_uses,
    )
    slots = _validate_acquisitions(
        validated_program.acquisition_slots,
        acquisition_uses,
        issues,
    )
    _validate_overlaps(placed, issues)
    if issues:
        raise PulseValidationError(_stable_issues(issues))

    events = tuple(
        ScheduledPulseEvent(
            id=event.leaf.id,
            start_seconds=event.start,
            duration_seconds=event.duration,
            instruction=event.leaf,
        )
        for event in _ordered_placed_leaves(placed)
    )
    return ScheduledPulseProgram(
        id=validated_program.id,
        duration_seconds=duration,
        events=events,
        acquisition_slots=slots,
    )


schedule_pulse_program = schedule


__all__ = [
    "DRAG",
    "Acquire",
    "AcquireSignal",
    "AcquisitionSlot",
    "AnalyticEnvelope",
    "Barrier",
    "Constant",
    "Delay",
    "DriveSignal",
    "FluxSignal",
    "FrameSignal",
    "Gaussian",
    "LogicalSignal",
    "Parallel",
    "Play",
    "PlaySignal",
    "PulseInstruction",
    "PulseIssue",
    "PulseLeaf",
    "PulseProgram",
    "PulseValidationError",
    "ReadoutSignal",
    "ScheduledPulseEvent",
    "ScheduledPulseProgram",
    "Sequence",
    "ShiftPhase",
    "iter_pulse_leaves",
    "schedule",
    "schedule_pulse_program",
]

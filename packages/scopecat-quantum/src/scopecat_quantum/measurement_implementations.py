"""Resolved pulse implementations for logical measurements."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash

from scopecat_quantum._ids import (
    CircuitOperationId,
    PulseImplementationId,
    QubitId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.circuits import Measure
from scopecat_quantum.pulses import (
    Acquire,
    AcquireSignal,
    Play,
    PulseLeaf,
    PulseProgram,
    ReadoutSignal,
    iter_pulse_leaves,
    pulse_leaf_owners,
)


@dataclass(frozen=True, slots=True)
class MeasurementPulseImplementationKey:
    """Reusable logical identity of one single-qubit measurement shape."""

    qubit: QubitId
    acquisition_kind: AcquisitionKind

    @classmethod
    def from_measurement(
        cls, measurement: Measure
    ) -> MeasurementPulseImplementationKey:
        """Return the implementation key of one measurement occurrence."""

        return cls(
            qubit=measurement.qubit,
            acquisition_kind=measurement.acquisition_kind,
        )


def _measurement_template_leaves(
    pulse_template: PulseProgram,
    key: MeasurementPulseImplementationKey,
    *,
    subject: str,
) -> tuple[PulseLeaf, ...]:
    """Validate and expose the measurement-specific refinement contract."""

    slots = pulse_template.acquisition_slots
    if len(slots) != 1:
        msg = f"{subject} pulse template must declare exactly one acquisition slot"
        raise ValueError(msg)
    slot = slots[0]
    if slot.kind is not key.acquisition_kind:
        msg = f"{subject} acquisition slot kind must match its implementation key"
        raise ValueError(msg)
    expected_acquire_signal = AcquireSignal(key.qubit)
    if slot.signal != expected_acquire_signal:
        msg = f"{subject} acquisition slot signal must match its implementation qubit"
        raise ValueError(msg)

    leaves = tuple(iter_pulse_leaves(pulse_template.body))
    event_ids = tuple(leaf.id for leaf in leaves)
    if len(set(event_ids)) != len(event_ids):
        msg = f"{subject} pulse template event ids must be unique"
        raise ValueError(msg)

    acquires = tuple(leaf for leaf in leaves if isinstance(leaf, Acquire))
    if len(acquires) != 1:
        msg = f"{subject} pulse template must contain exactly one Acquire instruction"
        raise ValueError(msg)
    acquire = acquires[0]
    if acquire.slot_id != slot.id:
        msg = f"{subject} Acquire instruction must close its declared acquisition slot"
        raise ValueError(msg)
    if acquire.signal != expected_acquire_signal:
        msg = f"{subject} Acquire signal must match its implementation qubit"
        raise ValueError(msg)

    expected_readout_signal = ReadoutSignal(key.qubit)
    if not any(
        isinstance(leaf, Play) and leaf.signal == expected_readout_signal
        for leaf in leaves
    ):
        msg = (
            f"{subject} pulse template must play its implementation qubit "
            "readout signal"
        )
        raise ValueError(msg)
    foreign_owners = set(pulse_leaf_owners(pulse_template.body)) - {key.qubit}
    if foreign_owners:
        rendered = ", ".join(
            repr(owner.value)
            for owner in sorted(foreign_owners, key=lambda item: item.value)
        )
        msg = f"{subject} contains unauthorized signal owners: {rendered}"
        raise ValueError(msg)
    return leaves


@dataclass(frozen=True, slots=True)
class MeasurementPulseImplementation:
    """One resolved measurement implementation with a reusable pulse template."""

    id: PulseImplementationId
    key: MeasurementPulseImplementationKey
    pulse_template: PulseProgram

    def __post_init__(self) -> None:
        _measurement_template_leaves(
            self.pulse_template,
            self.key,
            subject="measurement implementation",
        )

    @property
    def fingerprint(self) -> str:
        """Identify the exact resolved template, including point-effective values."""

        return stable_content_hash(content_fingerprint(self))


@dataclass(frozen=True, slots=True)
class MeasurementPulseImplementationBinding:
    """Resolved pulse template bound to one logical measurement occurrence."""

    measurement_id: CircuitOperationId
    key: MeasurementPulseImplementationKey
    implementation_id: PulseImplementationId
    implementation_fingerprint: str
    pulse_template: PulseProgram

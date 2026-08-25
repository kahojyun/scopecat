"""Resolved pulse implementations for logical measurements."""

from __future__ import annotations

from dataclasses import dataclass, field

from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash

from scopecat_quantum._ids import (
    CircuitOperationId,
    PulseImplementationId,
    QubitId,
)
from scopecat_quantum.acquisitions import (
    QuantumResultContract,
)
from scopecat_quantum.circuits import Measure
from scopecat_quantum.pulses import (
    AcquireSignal,
    Play,
    PulseProgram,
    ReadoutSignal,
    pulse_leaf_owners,
    schedule,
)


@dataclass(frozen=True, slots=True)
class MeasurementPulseImplementationKey:
    """Reusable logical identity of one single-qubit measurement shape."""

    qubit: QubitId
    contract: QuantumResultContract

    @classmethod
    def from_measurement(
        cls, measurement: Measure
    ) -> MeasurementPulseImplementationKey:
        """Return the implementation key of one measurement occurrence."""

        return cls(
            qubit=measurement.qubit,
            contract=measurement.contract,
        )


def _validate_measurement_template(
    pulse_template: PulseProgram,
    key: MeasurementPulseImplementationKey,
) -> None:
    """Validate only the measurement refinement of a canonical pulse program."""

    scheduled = schedule(pulse_template)
    slots = scheduled.acquisition_slots
    if len(slots) != 1:
        msg = "measurement implementation must declare exactly one acquisition slot"
        raise ValueError(msg)
    slot = slots[0]
    if slot.contract != key.contract:
        msg = "measurement acquisition slot contract must match its implementation key"
        raise ValueError(msg)
    expected_acquire_signal = AcquireSignal(key.qubit)
    if slot.signal != expected_acquire_signal:
        msg = "measurement acquisition slot signal must match its implementation qubit"
        raise ValueError(msg)

    expected_readout_signal = ReadoutSignal(key.qubit)
    if not any(
        isinstance(event.instruction, Play)
        and event.instruction.signal == expected_readout_signal
        for event in scheduled.events
    ):
        msg = (
            "measurement implementation must play its implementation qubit "
            "readout signal"
        )
        raise ValueError(msg)
    foreign_owners = set(pulse_leaf_owners(pulse_template.body)) - {key.qubit}
    if foreign_owners:
        rendered = ", ".join(
            repr(owner.value)
            for owner in sorted(foreign_owners, key=lambda item: item.value)
        )
        msg = f"measurement implementation has unauthorized signal owners: {rendered}"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class MeasurementPulseImplementation:
    """One resolved measurement implementation with a reusable pulse template."""

    id: PulseImplementationId
    key: MeasurementPulseImplementationKey
    pulse_template: PulseProgram
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_measurement_template(self.pulse_template, self.key)
        object.__setattr__(
            self,
            "fingerprint",
            stable_content_hash(
                content_fingerprint(
                    {
                        "schema": (
                            "scopecat_quantum.measurement_pulse_implementation.v1"
                        ),
                        "id": self.id,
                        "key": self.key,
                        "pulse_template": self.pulse_template,
                    }
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class MeasurementPulseImplementationBinding:
    """Resolved pulse template bound to one logical measurement occurrence."""

    measurement_id: CircuitOperationId
    key: MeasurementPulseImplementationKey
    implementation_id: PulseImplementationId
    implementation_fingerprint: str
    pulse_template: PulseProgram

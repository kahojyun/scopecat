from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from scopecat import Quantity

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CircuitOperationId,
    PulseEventId,
    PulseImplementationId,
    PulseProgramId,
    QubitId,
)
from scopecat_quantum.acquisitions import (
    INTEGRATED_IQ_RESULT,
    AcquisitionKind,
    QuantumResultContract,
    QuantumResultDimension,
)
from scopecat_quantum.circuits import Measure
from scopecat_quantum.measurement_implementations import (
    MeasurementPulseImplementation,
    MeasurementPulseImplementationBinding,
    MeasurementPulseImplementationKey,
)
from scopecat_quantum.pulses import (
    Acquire,
    AcquireSignal,
    AcquisitionSlot,
    Constant,
    Play,
    PulseProgram,
    ReadoutSignal,
)
from scopecat_quantum.pulses import (
    Parallel as PulseParallel,
)
from scopecat_quantum.pulses import (
    Sequence as PulseSequence,
)

Q0 = QubitId("q0")
Q1 = QubitId("q1")


def _contract(
    kind: AcquisitionKind,
    dimensions: tuple[QuantumResultDimension, ...] | None = None,
) -> QuantumResultContract:
    selected_dimensions = dimensions
    if selected_dimensions is None:
        selected_dimensions = (
            (QuantumResultDimension("sample", "sample", 128),)
            if kind is AcquisitionKind.RAW_TRACE
            else ()
        )
    return QuantumResultContract(
        acquisition_kind=kind,
        dtype=("int64" if kind is AcquisitionKind.CLASSIFIED_STATE else "complex128"),
        unit=(None if kind is AcquisitionKind.CLASSIFIED_STATE else "ratio"),
        dimensions=selected_dimensions,
    )


def _envelope() -> Constant:
    return Constant(
        duration=Quantity(500, "ns"),
        amplitude=Quantity(0.2, "ratio"),
    )


def _key(
    *,
    qubit: QubitId = Q0,
    kind: AcquisitionKind = AcquisitionKind.INTEGRATED_IQ,
    dimensions: tuple[QuantumResultDimension, ...] | None = None,
) -> MeasurementPulseImplementationKey:
    return MeasurementPulseImplementationKey(
        qubit=qubit,
        contract=_contract(kind, dimensions),
    )


def _template(
    *,
    qubit: QubitId = Q0,
    kind: AcquisitionKind = AcquisitionKind.INTEGRATED_IQ,
    dimensions: tuple[QuantumResultDimension, ...] | None = None,
    program_id: PulseProgramId | None = None,
    readout_event_id: PulseEventId | None = None,
    acquire_event_id: PulseEventId | None = None,
) -> PulseProgram:
    signal = AcquireSignal(qubit)
    slot = AcquisitionSlot(
        id=AcquisitionSlotId("result"),
        contract=_contract(kind, dimensions),
        signal=signal,
    )
    return PulseProgram(
        id=program_id or PulseProgramId("measurement-template"),
        body=PulseParallel(
            (
                Play(
                    id=readout_event_id or PulseEventId("readout"),
                    signal=ReadoutSignal(qubit),
                    envelope=_envelope(),
                ),
                Acquire(
                    id=acquire_event_id or PulseEventId("acquire"),
                    signal=signal,
                    slot_id=slot.id,
                    duration=Quantity(500, "ns"),
                ),
            )
        ),
        acquisition_slots=(slot,),
    )


def _implementation(
    implementation_id: str = "readout-q0",
    *,
    key: MeasurementPulseImplementationKey | None = None,
    pulse_template: PulseProgram | None = None,
) -> MeasurementPulseImplementation:
    return MeasurementPulseImplementation(
        id=PulseImplementationId(implementation_id),
        key=key or _key(),
        pulse_template=pulse_template or _template(),
    )


def _binding(
    measurement_id: str = "measure-q0",
    *,
    implementation: MeasurementPulseImplementation | None = None,
) -> MeasurementPulseImplementationBinding:
    selected = implementation or _implementation()
    return MeasurementPulseImplementationBinding(
        measurement_id=CircuitOperationId(measurement_id),
        key=selected.key,
        implementation_id=selected.id,
        implementation_fingerprint=selected.fingerprint,
        pulse_template=selected.pulse_template,
    )


def test_measurement_implementation_key_contains_only_reusable_logical_data() -> None:
    key = MeasurementPulseImplementationKey(
        qubit=Q0,
        contract=INTEGRATED_IQ_RESULT,
    )

    assert key == MeasurementPulseImplementationKey(Q0, INTEGRATED_IQ_RESULT)


def test_measurement_implementation_key_snapshots_measurement_semantics() -> None:
    measurement = Measure(
        id=CircuitOperationId("measure"),
        qubit=Q1,
        acquisition_slot_id=AcquisitionSlotId("result"),
        contract=INTEGRATED_IQ_RESULT,
    )

    key = MeasurementPulseImplementationKey.from_measurement(measurement)

    assert key == MeasurementPulseImplementationKey(Q1, INTEGRATED_IQ_RESULT)


def test_measurement_implementation_accepts_exact_single_slot_template() -> None:
    pulse_template = _template()

    implementation = _implementation(pulse_template=pulse_template)
    binding = _binding(implementation=implementation)

    assert implementation.pulse_template is pulse_template
    assert binding.pulse_template is pulse_template
    assert binding.key == implementation.key


def test_measurement_implementation_requires_exact_result_dimensions() -> None:
    dimensions = (QuantumResultDimension("round", "round", 3),)

    with pytest.raises(ValueError, match="contract must match"):
        _implementation(
            key=_key(dimensions=dimensions),
            pulse_template=_template(),
        )


@given(
    qubit_index=st.integers(min_value=0, max_value=1000),
    kind=st.sampled_from(tuple(AcquisitionKind)),
    readout_index=st.integers(min_value=0, max_value=1000),
    acquire_index=st.integers(min_value=1001, max_value=2000),
    scope_depth=st.integers(min_value=0, max_value=4),
)
def test_valid_template_contract_is_independent_of_identity_spelling(
    qubit_index: int,
    kind: AcquisitionKind,
    readout_index: int,
    acquire_index: int,
    scope_depth: int,
) -> None:
    qubit = QubitId(f"q-{qubit_index}")
    scope = tuple(f"scope-{index}" for index in range(scope_depth))
    pulse_template = _template(
        qubit=qubit,
        kind=kind,
        readout_event_id=PulseEventId(f"event-{readout_index}", scope=scope),
        acquire_event_id=PulseEventId(f"event-{acquire_index}", scope=scope),
    )

    implementation = _implementation(
        key=_key(qubit=qubit, kind=kind),
        pulse_template=pulse_template,
    )

    assert implementation.key == MeasurementPulseImplementationKey(
        qubit,
        _contract(kind),
    )


@pytest.mark.parametrize("slot_count", [0, 2])
def test_template_requires_exactly_one_declared_slot(slot_count: int) -> None:
    signal = AcquireSignal(Q0)
    slots = tuple(
        AcquisitionSlot(
            id=AcquisitionSlotId(f"result-{index}"),
            contract=INTEGRATED_IQ_RESULT,
            signal=signal,
        )
        for index in range(slot_count)
    )
    pulse_template = PulseProgram(
        id=PulseProgramId("measurement-template"),
        body=PulseSequence(
            (
                Play(
                    id=PulseEventId("readout"),
                    signal=ReadoutSignal(Q0),
                    envelope=_envelope(),
                ),
                *(
                    Acquire(
                        id=PulseEventId(f"acquire-{index}"),
                        signal=signal,
                        slot_id=slot.id,
                        duration=Quantity(500, "ns"),
                    )
                    for index, slot in enumerate(slots)
                ),
            )
        ),
        acquisition_slots=slots,
    )

    with pytest.raises(ValueError, match="exactly one acquisition slot"):
        _implementation(pulse_template=pulse_template)


def test_template_slot_signal_must_match_key_qubit() -> None:
    with pytest.raises(ValueError, match="slot signal must match"):
        _implementation(pulse_template=_template(qubit=Q1))


def test_template_requires_matching_readout_play() -> None:
    slot = AcquisitionSlot(
        id=AcquisitionSlotId("result"),
        contract=INTEGRATED_IQ_RESULT,
        signal=AcquireSignal(Q0),
    )
    pulse_template = PulseProgram(
        id=PulseProgramId("measurement-template"),
        body=Acquire(
            id=PulseEventId("acquire"),
            signal=slot.signal,
            slot_id=slot.id,
            duration=Quantity(500, "ns"),
        ),
        acquisition_slots=(slot,),
    )

    with pytest.raises(
        ValueError, match="play its implementation qubit readout signal"
    ):
        _implementation(pulse_template=pulse_template)

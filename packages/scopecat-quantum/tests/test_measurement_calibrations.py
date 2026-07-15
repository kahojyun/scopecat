from __future__ import annotations

from typing import cast

import pytest
from hypothesis import given
from hypothesis import strategies as st
from scopecat import Quantity

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CalibrationId,
    CircuitOperationId,
    PulseEventId,
    PulseProgramId,
    QubitId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.circuits import Measure
from scopecat_quantum.measurement_calibrations import (
    MeasurementCalibration,
    MeasurementCalibrationBinding,
    MeasurementCalibrationCatalog,
    MeasurementCalibrationKey,
)
from scopecat_quantum.pulses import (
    Acquire,
    AcquireSignal,
    AcquisitionSlot,
    Constant,
    Delay,
    DriveSignal,
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


def _envelope() -> Constant:
    return Constant(
        duration=Quantity(500, "ns"),
        amplitude=Quantity(0.2, "ratio"),
    )


def _key(
    *,
    qubit: QubitId = Q0,
    kind: AcquisitionKind = AcquisitionKind.INTEGRATED_IQ,
) -> MeasurementCalibrationKey:
    return MeasurementCalibrationKey(qubit=qubit, acquisition_kind=kind)


def _template(
    *,
    qubit: QubitId = Q0,
    kind: AcquisitionKind = AcquisitionKind.INTEGRATED_IQ,
    program_id: PulseProgramId | None = None,
    readout_event_id: PulseEventId | None = None,
    acquire_event_id: PulseEventId | None = None,
) -> PulseProgram:
    signal = AcquireSignal(qubit)
    slot = AcquisitionSlot(
        id=AcquisitionSlotId("result"),
        kind=kind,
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


def _calibration(
    calibration_id: str = "readout-q0",
    *,
    key: MeasurementCalibrationKey | None = None,
    pulse_template: PulseProgram | None = None,
) -> MeasurementCalibration:
    return MeasurementCalibration(
        id=CalibrationId(calibration_id),
        key=key or _key(),
        pulse_template=pulse_template or _template(),
    )


def _binding(
    measurement_id: str = "measure-q0",
    *,
    calibration: MeasurementCalibration | None = None,
) -> MeasurementCalibrationBinding:
    selected = calibration or _calibration()
    return MeasurementCalibrationBinding(
        measurement_id=CircuitOperationId(measurement_id),
        key=selected.key,
        calibration_id=selected.id,
        pulse_template=selected.pulse_template,
    )


def test_measurement_calibration_key_contains_only_reusable_logical_data() -> None:
    key = MeasurementCalibrationKey(
        qubit=Q0,
        acquisition_kind=AcquisitionKind.RAW_TRACE,
    )

    assert key == MeasurementCalibrationKey(Q0, AcquisitionKind.RAW_TRACE)


def test_measurement_calibration_key_snapshots_measurement_semantics() -> None:
    measurement = Measure(
        id=CircuitOperationId("measure"),
        qubit=Q1,
        acquisition_slot_id=AcquisitionSlotId("result"),
        acquisition_kind=AcquisitionKind.RAW_TRACE,
    )

    key = MeasurementCalibrationKey.from_measurement(measurement)

    assert key == MeasurementCalibrationKey(Q1, AcquisitionKind.RAW_TRACE)


def test_measurement_calibration_accepts_exact_single_slot_template() -> None:
    pulse_template = _template()

    calibration = _calibration(pulse_template=pulse_template)
    binding = _binding(calibration=calibration)

    assert calibration.pulse_template is pulse_template
    assert binding.pulse_template is pulse_template
    assert binding.key == calibration.key


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

    calibration = _calibration(
        key=_key(qubit=qubit, kind=kind),
        pulse_template=pulse_template,
    )

    assert calibration.key == MeasurementCalibrationKey(qubit, kind)


@pytest.mark.parametrize("slot_count", [0, 2])
def test_template_requires_exactly_one_declared_slot(slot_count: int) -> None:
    pulse_template = _template()
    slot = pulse_template.acquisition_slots[0]
    object.__setattr__(pulse_template, "acquisition_slots", (slot,) * slot_count)

    with pytest.raises(ValueError, match="exactly one acquisition slot"):
        _calibration(pulse_template=pulse_template)


def test_template_slot_kind_must_match_key() -> None:
    pulse_template = _template(kind=AcquisitionKind.RAW_TRACE)

    with pytest.raises(ValueError, match="slot kind must match"):
        _calibration(key=_key(), pulse_template=pulse_template)


def test_template_slot_signal_must_match_key_qubit() -> None:
    pulse_template = _template()
    slot = pulse_template.acquisition_slots[0]
    object.__setattr__(slot, "signal", AcquireSignal(Q1))

    with pytest.raises(ValueError, match="slot signal must match"):
        _calibration(pulse_template=pulse_template)


@pytest.mark.parametrize("acquire_count", [0, 2])
def test_template_requires_exactly_one_acquire(acquire_count: int) -> None:
    pulse_template = _template()
    readout, acquire = cast("PulseParallel", pulse_template.body).branches
    acquires = tuple(
        Acquire(
            id=PulseEventId(f"acquire-{index}"),
            signal=cast("Acquire", acquire).signal,
            slot_id=cast("Acquire", acquire).slot_id,
            duration=cast("Acquire", acquire).duration,
        )
        for index in range(acquire_count)
    )
    object.__setattr__(pulse_template, "body", PulseSequence((readout, *acquires)))

    with pytest.raises(ValueError, match="exactly one Acquire"):
        _calibration(pulse_template=pulse_template)


def test_template_acquire_must_close_declared_slot() -> None:
    pulse_template = _template()
    acquire = cast("PulseParallel", pulse_template.body).branches[1]
    object.__setattr__(acquire, "slot_id", AcquisitionSlotId("other"))

    with pytest.raises(ValueError, match="close its declared acquisition slot"):
        _calibration(pulse_template=pulse_template)


def test_template_acquire_signal_must_match_key_qubit() -> None:
    pulse_template = _template()
    acquire = cast("PulseParallel", pulse_template.body).branches[1]
    object.__setattr__(acquire, "signal", AcquireSignal(Q1))

    with pytest.raises(ValueError, match="Acquire signal must match"):
        _calibration(pulse_template=pulse_template)


def test_template_requires_matching_readout_play() -> None:
    pulse_template = _template()
    readout, acquire = cast("PulseParallel", pulse_template.body).branches
    object.__setattr__(readout, "signal", ReadoutSignal(Q1))

    with pytest.raises(ValueError, match="play its calibration qubit readout signal"):
        _calibration(pulse_template=pulse_template)

    object.__setattr__(
        pulse_template,
        "body",
        PulseSequence(
            (
                Delay(PulseEventId("delay"), DriveSignal(Q0), Quantity(5, "ns")),
                acquire,
            )
        ),
    )
    with pytest.raises(ValueError, match="play its calibration qubit readout signal"):
        _calibration(pulse_template=pulse_template)


@given(duplicate_local_id=st.integers(min_value=0, max_value=10_000))
def test_template_rejects_duplicate_structural_event_identity(
    duplicate_local_id: int,
) -> None:
    duplicate = PulseEventId(
        f"event-{duplicate_local_id}",
        scope=("template",),
    )
    pulse_template = _template(
        readout_event_id=duplicate,
        acquire_event_id=duplicate,
    )

    with pytest.raises(ValueError, match="event ids must be unique"):
        _calibration(pulse_template=pulse_template)


def test_template_accepts_same_local_event_id_in_distinct_structural_scopes() -> None:
    pulse_template = _template(
        readout_event_id=PulseEventId("event", scope=("readout",)),
        acquire_event_id=PulseEventId("event", scope=("acquire",)),
    )

    assert _calibration(pulse_template=pulse_template).pulse_template is pulse_template


@given(order=st.permutations(("z", "a", "m")))
def test_catalog_order_does_not_affect_canonical_entries(
    order: list[str],
) -> None:
    entries = tuple(_calibration(calibration_id) for calibration_id in order)

    catalog = MeasurementCalibrationCatalog(entries)

    assert tuple(entry.id.value for entry in catalog.entries) == ("a", "m", "z")


def test_catalog_allows_same_key_but_rejects_duplicate_calibration_identity() -> None:
    first = _calibration("first")
    second = _calibration("second")

    assert len(MeasurementCalibrationCatalog((first, second)).entries) == 2
    with pytest.raises(ValueError, match="ids must be unique"):
        MeasurementCalibrationCatalog((first, first))

from __future__ import annotations

import copy
from typing import cast

import pytest
from hypothesis import given
from hypothesis import strategies as st
from scopecat import Quantity

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    CalibrationId,
    CircuitId,
    CircuitOperationId,
    PulseEventId,
    PulseProgramId,
    QubitId,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetId,
)
from scopecat_quantum.acquisitions import AcquisitionKind
from scopecat_quantum.calibrations import (
    CalibrationCatalog,
    CalibrationSelection,
    select_calibrations,
)
from scopecat_quantum.circuit_targets import (
    CircuitTargetAcquisitionOrigin,
    CircuitTargetEventOrigin,
    PreparedCircuitTargetBatch,
    PreparedCircuitTargetEntry,
    prepare_circuit_target_batch,
    prepare_circuit_target_entry,
)
from scopecat_quantum.circuits import (
    CircuitProgram,
    Measure,
    VerifiedCircuitProgram,
    verify_circuit_program,
)
from scopecat_quantum.circuits import Sequence as CircuitSequence
from scopecat_quantum.measurement_calibrations import (
    MeasurementCalibration,
    MeasurementCalibrationCatalog,
    MeasurementCalibrationKey,
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
from scopecat_quantum.pulses import Parallel as PulseParallel
from scopecat_quantum.targets import (
    TargetAcquisitionAddress,
    TargetCompileEntry,
    TargetEventAddress,
)

Q0 = QubitId("q0")


def _verified_and_selection(
    *,
    circuit_id: str = "shared-circuit",
    measurement_count: int = 1,
) -> tuple[VerifiedCircuitProgram, CalibrationSelection]:
    measurements = tuple(
        Measure(
            id=CircuitOperationId(f"measure-{index}"),
            qubit=Q0,
            acquisition_slot_id=AcquisitionSlotId(f"result-{index}"),
            acquisition_kind=AcquisitionKind.INTEGRATED_IQ,
        )
        for index in range(measurement_count)
    )
    verified = verify_circuit_program(
        CircuitProgram(
            id=CircuitId(circuit_id),
            body=CircuitSequence(measurements),
        ),
        (),
    )
    template_slot = AcquisitionSlot(
        id=AcquisitionSlotId("template-result"),
        kind=AcquisitionKind.INTEGRATED_IQ,
        signal=AcquireSignal(Q0),
    )
    template = PulseProgram(
        id=PulseProgramId("readout-template"),
        body=PulseParallel(
            (
                Play(
                    id=PulseEventId("readout"),
                    signal=ReadoutSignal(Q0),
                    envelope=Constant(
                        duration=Quantity(4, "ns"),
                        amplitude=Quantity(0.2, "arb"),
                    ),
                ),
                Acquire(
                    id=PulseEventId("acquire"),
                    signal=AcquireSignal(Q0),
                    slot_id=template_slot.id,
                    duration=Quantity(4, "ns"),
                ),
            )
        ),
        acquisition_slots=(template_slot,),
    )
    calibration = MeasurementCalibration(
        id=CalibrationId("readout-q0"),
        key=MeasurementCalibrationKey(
            Q0,
            AcquisitionKind.INTEGRATED_IQ,
        ),
        pulse_template=template,
    )
    selection = select_calibrations(
        verified,
        CalibrationCatalog(
            measurements=MeasurementCalibrationCatalog((calibration,)),
        ),
    )
    return verified, selection


def _prepared(
    entry_id: str,
    *,
    circuit: VerifiedCircuitProgram | None = None,
    selection: CalibrationSelection | None = None,
    measurement_count: int = 1,
) -> PreparedCircuitTargetEntry:
    if circuit is None or selection is None:
        circuit, selection = _verified_and_selection(
            measurement_count=measurement_count
        )
    return prepare_circuit_target_entry(
        TargetCompileEntryId(entry_id),
        circuit,
        selection,
        output_id=PulseProgramId("prepared-pulses"),
    )


def _batch(
    entries: tuple[PreparedCircuitTargetEntry, ...],
) -> PreparedCircuitTargetBatch:
    return prepare_circuit_target_batch(
        entries,
        target_id=TargetId("target"),
        compiler_id=TargetCompilerId("compiler.v1"),
        capability_fingerprint="capabilities:v1",
        repetitions=3,
    )


def test_prepared_entry_exports_the_complete_refinement_chain() -> None:
    circuit, selection = _verified_and_selection(measurement_count=2)

    prepared = _prepared("entry", circuit=circuit, selection=selection)

    assert prepared.circuit is circuit
    assert prepared.selection is selection
    assert prepared.source_circuit_id == circuit.program.id
    assert prepared.lowered.source_circuit_id == circuit.program.id
    assert prepared.scheduled.id == prepared.lowered.program.id
    assert prepared.target_entry == TargetCompileEntry(
        TargetCompileEntryId("entry"),
        prepared.scheduled,
    )
    assert prepared.event_addresses == prepared.target_entry.event_addresses
    assert prepared.acquisition_addresses == prepared.target_entry.acquisition_addresses
    assert len(prepared.event_origins) == 4
    assert len(prepared.acquisition_origins) == 2

    for origin in prepared.event_origins:
        assert origin.source_circuit_id == circuit.program.id
        assert origin.provenance is prepared.lowered.provenance_for(
            origin.address.event_id
        )
        assert prepared.event_origin_for(origin.address) is origin
    for origin in prepared.acquisition_origins:
        assert origin.source_circuit_id == circuit.program.id
        assert origin.provenance is prepared.lowered.acquisition_provenance_for(
            origin.address.slot_id
        )
        assert prepared.acquisition_origin_for(origin.address) is origin


@given(st.integers(min_value=1, max_value=6))
def test_entry_origin_coverage_is_exact_for_every_measurement(count: int) -> None:
    prepared = _prepared("entry", measurement_count=count)

    assert len(prepared.event_origins) == count * 2
    assert len(prepared.acquisition_origins) == count
    assert tuple(origin.address for origin in prepared.event_origins) == (
        prepared.target_entry.event_addresses
    )
    assert tuple(origin.address for origin in prepared.acquisition_origins) == (
        prepared.target_entry.acquisition_addresses
    )
    assert {
        origin.provenance.measurement_id for origin in prepared.acquisition_origins
    } == {CircuitOperationId(f"measure-{index}") for index in range(count)}


@given(
    st.lists(
        st.integers(min_value=0, max_value=100),
        min_size=1,
        max_size=7,
        unique=True,
    )
)
def test_batch_preserves_semantic_order_and_entry_qualifies_reused_ids(
    labels: list[int],
) -> None:
    circuit, selection = _verified_and_selection()
    entries = tuple(
        _prepared(
            f"entry-{label}",
            circuit=circuit,
            selection=selection,
        )
        for label in labels
    )

    batch = _batch(entries)

    assert tuple(entry.id for entry in batch.entries) == tuple(
        TargetCompileEntryId(f"entry-{label}") for label in labels
    )
    assert batch.request.entries == tuple(entry.target_entry for entry in entries)
    assert batch.event_addresses == tuple(
        address for entry in entries for address in entry.event_addresses
    )
    assert batch.acquisition_addresses == tuple(
        address for entry in entries for address in entry.acquisition_addresses
    )
    assert len(set(batch.event_addresses)) == len(batch.event_addresses)
    assert len(set(batch.acquisition_addresses)) == len(batch.acquisition_addresses)
    assert len({address.event_id for address in batch.event_addresses}) == 2
    assert len({address.slot_id for address in batch.acquisition_addresses}) == 1
    for entry in entries:
        assert batch.entry_for(entry.id) is entry
    for origin in batch.event_origins:
        assert batch.event_origin_for(origin.address) is origin
    for origin in batch.acquisition_origins:
        assert batch.acquisition_origin_for(origin.address) is origin


def test_batch_request_and_origins_have_exact_ordered_coverage() -> None:
    first = _prepared("first", measurement_count=2)
    second = _prepared("second", measurement_count=3)

    batch = _batch((second, first))

    assert batch.request.target_id == TargetId("target")
    assert batch.request.compiler_id == TargetCompilerId("compiler.v1")
    assert batch.request.capability_fingerprint == "capabilities:v1"
    assert batch.request.repetitions == 3
    assert tuple(origin.address for origin in batch.event_origins) == (
        batch.request.event_addresses
    )
    assert tuple(origin.address for origin in batch.acquisition_origins) == (
        batch.request.acquisition_addresses
    )
    assert tuple(origin.source_circuit_id for origin in batch.event_origins) == (
        *((second.source_circuit_id,) * len(second.event_origins)),
        *((first.source_circuit_id,) * len(first.event_origins)),
    )


def test_origin_wrappers_cannot_be_forged_independently() -> None:
    prepared = _prepared("entry")
    event_provenance = prepared.event_origins[0].provenance
    acquisition_provenance = prepared.acquisition_origins[0].provenance

    with pytest.raises(TypeError, match="only be created"):
        CircuitTargetEventOrigin(
            prepared.source_circuit_id,
            prepared.event_addresses[0],
            event_provenance,
        )
    with pytest.raises(TypeError, match="only be created"):
        CircuitTargetAcquisitionOrigin(
            prepared.source_circuit_id,
            prepared.acquisition_addresses[0],
            acquisition_provenance,
        )


def test_factories_reject_wrong_runtime_identity_spaces_and_shapes() -> None:
    circuit, selection = _verified_and_selection()
    with pytest.raises(TypeError, match="TargetCompileEntryId"):
        prepare_circuit_target_entry(
            cast("TargetCompileEntryId", TargetId("wrong-space")),
            circuit,
            selection,
            output_id=PulseProgramId("output"),
        )
    with pytest.raises(TypeError, match="VerifiedCircuitProgram"):
        prepare_circuit_target_entry(
            TargetCompileEntryId("entry"),
            cast("VerifiedCircuitProgram", circuit.program),
            selection,
            output_id=PulseProgramId("output"),
        )
    with pytest.raises(TypeError, match="CalibrationSelection"):
        prepare_circuit_target_entry(
            TargetCompileEntryId("entry"),
            circuit,
            cast("CalibrationSelection", object()),
            output_id=PulseProgramId("output"),
        )
    with pytest.raises(TypeError, match="PulseProgramId"):
        prepare_circuit_target_entry(
            TargetCompileEntryId("entry"),
            circuit,
            selection,
            output_id=cast("PulseProgramId", CircuitId("wrong-space")),
        )
    with pytest.raises(TypeError, match="at least one"):
        _batch(cast("tuple[PreparedCircuitTargetEntry, ...]", (object(),)))


def test_sealed_constructors_cannot_be_used_as_proof_shortcuts() -> None:
    prepared = _prepared("entry")
    with pytest.raises(TypeError, match="can only be created"):
        PreparedCircuitTargetEntry(
            prepared.circuit,
            prepared.selection,
            prepared.lowered,
            prepared.scheduled,
            prepared.target_entry,
            prepared.event_origins,
            prepared.acquisition_origins,
        )
    with pytest.raises(TypeError, match="can only be created"):
        PreparedCircuitTargetBatch(
            (prepared,),
            _batch((prepared,)).request,
            prepared.event_origins,
            prepared.acquisition_origins,
        )


def test_batch_defensively_revalidates_retained_entry_congruence() -> None:
    prepared = copy.copy(_prepared("entry"))
    object.__setattr__(prepared, "event_origins", ())

    with pytest.raises(ValueError, match="exactly cover scheduled events"):
        _batch((prepared,))


def test_batch_rejects_a_mutated_origin_claim() -> None:
    prepared = copy.copy(_prepared("entry"))
    origin = copy.copy(prepared.acquisition_origins[0])
    object.__setattr__(origin, "source_circuit_id", CircuitId("foreign"))
    object.__setattr__(prepared, "acquisition_origins", (origin,))

    with pytest.raises(ValueError, match="exactly cover scheduled slots"):
        _batch((prepared,))


def test_duplicate_entry_addresses_fail_before_a_batch_is_returned() -> None:
    circuit, selection = _verified_and_selection()
    entries = (
        _prepared("duplicate", circuit=circuit, selection=selection),
        _prepared("duplicate", circuit=circuit, selection=selection),
    )

    with pytest.raises(ValueError, match="entry ids must be unique"):
        _batch(entries)


def test_address_lookups_reject_foreign_runtime_results() -> None:
    batch = _batch((_prepared("entry"),))

    with pytest.raises(KeyError, match="not in this batch"):
        batch.entry_for(TargetCompileEntryId("foreign"))
    with pytest.raises(KeyError, match="not in this batch"):
        batch.event_origin_for(
            TargetEventAddress(
                TargetCompileEntryId("foreign"),
                batch.event_addresses[0].event_id,
            )
        )
    with pytest.raises(KeyError, match="not in this batch"):
        batch.acquisition_origin_for(
            TargetAcquisitionAddress(
                TargetCompileEntryId("foreign"),
                batch.acquisition_addresses[0].slot_id,
            )
        )

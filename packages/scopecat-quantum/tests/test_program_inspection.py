from __future__ import annotations

from typing import Annotated

import scopecat as sc
from scopecat import Quantity
from scopecat.inspection import CompiledProgramInspectionQuery

from scopecat_quantum import authoring
from scopecat_quantum._ids import (
    AcquisitionSlotId,
    PulseEventId,
    PulseProgramId,
    QubitId,
)
from scopecat_quantum.acquisitions import INTEGRATED_IQ_RESULT
from scopecat_quantum.inspection import (
    QuantumInspectionBounds,
    build_quantum_program_inspection_snapshot,
)
from scopecat_quantum.pulses import (
    Acquire,
    AcquireSignal,
    AcquisitionSlot,
    PulseProgram,
    schedule,
)
from scopecat_quantum.pulses import Parallel as PulseParallel


def test_program_describe_and_draw_expose_the_authored_structure() -> None:
    x90 = authoring.single_qubit_gate("x90")

    @authoring.implementation(
        of=x90,
        candidate="x90.test",
        id="inspection.x90",
    )
    def x90_candidate(qubit: authoring.Qubit) -> authoring.QuantumFragment:
        return authoring.play(
            authoring.drive(qubit),
            authoring.constant(
                duration=Quantity(16, "ns"),
                amplitude=Quantity(0.2, "arb"),
            ),
        )

    @authoring.pulse_template(id="inspection.readout")
    def readout_pulse(qubit: authoring.Qubit) -> authoring.QuantumFragment:
        return authoring.play(
            authoring.readout(qubit),
            authoring.constant(
                duration=Quantity(24, "ns"),
                amplitude=Quantity(0.3, "arb"),
            ),
        )

    @authoring.program(id="inspection.example")
    def inspected_program(
        qubit: authoring.Qubit,
        rounds: Annotated[int, sc.IntType(minimum=1)],
    ) -> authoring.QuantumFragment:
        """Inspect one repeated candidate and parallel readout."""

        return authoring.sequence(
            authoring.repeat(x90_candidate(qubit), rounds),
            authoring.parallel(
                readout_pulse(qubit),
                authoring.acquire(
                    qubit,
                    duration=Quantity(24, "ns"),
                    result="iq",
                ),
            ),
        )

    assert (
        inspected_program.describe()
        == """\
program inspection.example
description:
  Inspect one repeated candidate and parallel readout.
ports:
  qubit: qubit
  rounds: Int
results:
  iq: integrated_iq complex128 ratio on qubit; axes=shot"""
    )
    assert (
        inspected_program.draw()
        == """\
program inspection.example
└─ sequence
   ├─ repeat $rounds
   │  └─ implementation x90(qubit) candidate='x90.test'
   │     └─ pulse inspection.x90
   │        └─ play drive(qubit) constant(duration=16 ns, amplitude=0.2 arb)
   └─ parallel
      ├─ pulse inspection.readout
      │  └─ play readout(qubit) constant(duration=24 ns, amplitude=0.3 arb)
      └─ acquire qubit duration=24 ns -> iq"""
    )
    assert authoring.describe(inspected_program) == inspected_program.describe()
    assert authoring.draw(inspected_program) == inspected_program.draw()

    bound = authoring.bind(
        inspected_program,
        {"qubit": "q7", "rounds": 3},
    )
    snapshot = build_quantum_program_inspection_snapshot(
        inspected_program,
        bound=bound,
        bounds=QuantumInspectionBounds(max_nodes_per_layer=64),
    )
    inspection = snapshot.project()
    assert tuple(layer.id for layer in inspection.layers) == ("authored", "logical")
    logical = inspection.layers[1]
    assert logical.node_count == len(logical.nodes)
    assert any(
        node.kind == "repeat" and node.label == "repeat x3" for node in logical.nodes
    )
    assert any(node.entity_ids == ("q7",) for node in logical.nodes)
    facts = {fact.id: fact.value for fact in logical.nodes[0].facts}
    assert facts["operation_count"] == 3
    assert facts["expanded_operation_count"] == 5
    assert facts["selected_entity_count"] == 1
    assert facts["max_parallel_width"] == 2

    filtered = snapshot.project(
        CompiledProgramInspectionQuery(
            layer_id="authored",
            kind="pulse",
            offset=1,
            limit=1,
        ),
    )
    authored = filtered.layers[0]
    assert filtered.schema_id == "scopecat.compiled_program_inspection.v3"
    assert authored.page.snapshot_id == filtered.snapshot_id
    assert authored.node_count > authored.page.matching_node_count
    assert authored.page.matching_node_count == 2
    assert authored.page.offset == 1
    assert authored.page.returned_node_count == 1
    assert authored.page.next_offset is None
    assert [node.kind for node in authored.nodes] == ["pulse"]
    assert filtered.layers[1].nodes == ()


def test_scheduled_inspection_separates_logical_results_from_acquisitions() -> None:
    @authoring.program(id="inspection.scheduled-results")
    def program(qubit: authoring.Qubit) -> authoring.QuantumFragment:
        return authoring.delay(authoring.drive(qubit), Quantity(1, "ns"))

    signals = tuple(AcquireSignal(QubitId(f"q{index}")) for index in range(2))
    slots = tuple(
        AcquisitionSlot(
            id=AcquisitionSlotId("iq", scope=(f"q{index}",)),
            contract=INTEGRATED_IQ_RESULT,
            signal=signal,
        )
        for index, signal in enumerate(signals)
    )
    scheduled = schedule(
        PulseProgram(
            id=PulseProgramId("scheduled-results"),
            body=PulseParallel(
                tuple(
                    Acquire(
                        id=PulseEventId("acquire", scope=(f"q{index}",)),
                        signal=signal,
                        slot_id=slot.id,
                        duration=Quantity(1, "ns"),
                    )
                    for index, (signal, slot) in enumerate(
                        zip(signals, slots, strict=True)
                    )
                )
            ),
            acquisition_slots=slots,
        )
    )

    inspection = build_quantum_program_inspection_snapshot(
        program,
        scheduled=scheduled,
    ).project(CompiledProgramInspectionQuery(layer_id="scheduled"))
    scheduled_layer = next(
        layer for layer in inspection.layers if layer.id == "scheduled"
    )
    root = scheduled_layer.nodes[0]

    assert root.result_ids == ("iq",)
    assert root.result_count == 1
    assert {fact.id: fact.value for fact in root.facts}["acquisition_count"] == 2

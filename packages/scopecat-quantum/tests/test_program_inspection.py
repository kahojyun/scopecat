from __future__ import annotations

from typing import Annotated

import scopecat as sc
from scopecat import Quantity

from scopecat_quantum import authoring
from scopecat_quantum.inspection import QuantumInspectionBounds, inspect_quantum_program


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
    inspection = inspect_quantum_program(
        inspected_program,
        bound=bound,
        bounds=QuantumInspectionBounds(max_nodes_per_layer=64),
    )
    assert tuple(layer.id for layer in inspection.layers) == ("authored", "logical")
    logical = inspection.layers[1]
    assert logical.node_count == len(logical.nodes)
    assert any(
        node.kind == "repeat" and node.label == "repeat x3" for node in logical.nodes
    )
    assert any(node.entity_ids == ("q7",) for node in logical.nodes)

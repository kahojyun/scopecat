"""Generate one composable sequence after length and seed bind per point."""

from __future__ import annotations

# %%
from typing import Annotated

import scopecat as sc
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.workflows.single_qubit_rb import (
    CLIFFORD_LENGTH,
    RB_SEED,
    single_qubit_rb_template,
)
from scopecat_quantum import authoring as q

_X = q.single_qubit_gate("x")
_Y = q.single_qubit_gate("y")


@q.fragment(id="notebook.seeded-sequence")
def seeded_sequence(
    qubit: q.Qubit,
    length: Annotated[int, sc.IntType(minimum=1)],
    seed: Annotated[int, sc.IntType(minimum=0)],
) -> q.QuantumFragment:
    """Expand concrete point values into an ordinary composable sequence."""

    return q.sequence(
        *(
            _X(qubit) if (seed + index) % 2 == 0 else _Y(qubit)
            for index in range(length)
        )
    )


@q.program(id="notebook.seeded-program")
def seeded_program(
    qubit: q.Qubit,
    length: Annotated[int, sc.IntType(minimum=1)],
    seed: Annotated[int, sc.IntType(minimum=0)],
) -> q.QuantumFragment:
    return q.sequence(
        seeded_sequence(qubit, length, seed),
        q.measure(qubit, result="iq"),
    )


# %%
# Binding one point expands exactly one fragment. A collection of programs is
# unnecessary: length and seed remain ordinary experiment axes.
bound_example = q.bind(
    seeded_program,
    {"qubit": "q0", "length": 4, "seed": 1},
)

lab = quantum_lab(workspace=notebook_workspace("authoring-point-bound-sequence"))
preview = (
    lab.prepare(single_qubit_rb_template())
    .scan(CLIFFORD_LENGTH, (4, 16))
    .scan(RB_SEED, (0, 1, 2))
    .preview(name="single-qubit Clifford RB")
)

# %%
point_bound_summary = {
    "fragment": seeded_sequence.id,
    "bound_program": bound_example.program.id.value,
    "scan_axes": preview.coordinate_ids,
    "points": preview.point_count,
}
print(point_bound_summary)

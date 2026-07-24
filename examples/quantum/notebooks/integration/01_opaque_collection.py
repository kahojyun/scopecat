"""Pass one collection through the opaque escape hatch as one point value."""

from __future__ import annotations

# %%
from typing import Annotated

import scopecat as sc
from quantum_lab_demo import EXAMPLE_ROOT
from quantum_lab_demo.scenarios.opaque_collection import (
    GATE_DURATION,
    PARALLEL_GATE_TABLE_TYPE,
    build_parallel_gate_set_program,
    resolve_parallel_gate_collection,
)


@sc.module
def opaque_parallel_gate_set(
    gates: Annotated[
        sc.Input[tuple[dict[str, str], ...]],
        PARALLEL_GATE_TABLE_TYPE,
    ],
):
    """Compile a whole table only when no domain compiler owns the semantics."""

    gates_ref = sc.input_ref(gates)
    gate_collection = resolve_parallel_gate_collection(gates_ref)
    program = sc.compute(
        "build-parallel-gate-set-program",
        fn=build_parallel_gate_set_program,
        output_type=sc.ScalarType(sc.PayloadType("gate_sequence")),
        inputs={
            # The collection is one compute input, not an experiment axis.
            "gates": gate_collection,
            "gate_duration": GATE_DURATION,
        },
    )
    return (
        sc.module_body()
        .resource(
            "drive",
            requires=("play_gate_sequence",),
            for_entities=(gate_collection.entities("control_qubit", "partner_qubit"),),
        )
        .computes(program)
        .bind_field(
            "drive",
            capability="play_gate_sequence",
            field="sequence",
            value=program.output,
        )
    )


@sc.template
def opaque_parallel_gate_template(
    gates: Annotated[
        sc.Input[tuple[dict[str, str], ...]],
        PARALLEL_GATE_TABLE_TYPE,
    ],
) -> sc.ExperimentBody:
    call = opaque_parallel_gate_set(gates=gates)
    return sc.experiment(call).scan(GATE_DURATION, [28], unit="ns")


# %%
parallel_gate_collection = (
    {"control_qubit": "q0", "partner_qubit": "q1", "gate": "cz"},
    {"control_qubit": "q2", "partner_qubit": "q3", "gate": "cz"},
)
lab = sc.open_project(EXAMPLE_ROOT).connect()
parallel_gate_preview = lab.prepare(
    opaque_parallel_gate_template(gates=parallel_gate_collection)
).preview()

# %%
opaque_collection_summary = {
    "collection_size": len(parallel_gate_collection),
    "points": parallel_gate_preview.point_count,
}
print(opaque_collection_summary)

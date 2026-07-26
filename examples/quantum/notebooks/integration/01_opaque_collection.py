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
)
from quantum_lab_demo.virtual_lab.parameters import two_qubit_gate_parameters

_QUBIT = sc.ScalarType(sc.EntityType(entity_kind="logical_qubit"))
_COUPLER = sc.ScalarType(sc.EntityType(entity_kind="logical_coupler"))
_QUBIT_SERIES = sc.SeriesType(_QUBIT)
_COUPLER_SERIES = sc.SeriesType(_COUPLER)


@sc.module
def opaque_parallel_gate_set(
    gates: Annotated[
        sc.Input[tuple[dict[str, str], ...]],
        PARALLEL_GATE_TABLE_TYPE,
    ],
    qubits: Annotated[sc.Input[tuple[str, ...]], _QUBIT_SERIES],
    couplers: Annotated[sc.Input[tuple[str, ...]], _COUPLER_SERIES],
):
    """Compile a whole table only when no domain compiler owns the semantics."""

    gates_ref = sc.input_ref(gates)
    # Routing precedes opaque compute, so its entity footprint stays explicit.
    qubits_ref = sc.input_ref(qubits)
    couplers_ref = sc.input_ref(couplers)
    program = sc.compute(
        "build-parallel-gate-set-program",
        fn=build_parallel_gate_set_program,
        output_type=sc.ScalarType(sc.PayloadType("gate_sequence")),
        inputs={
            # The collection is one compute input, not an experiment axis.
            "gates": gates_ref,
            "gate_parameters": two_qubit_gate_parameters(),
            "gate_duration": GATE_DURATION,
            "qubits": qubits_ref,
            "couplers": couplers_ref,
        },
    )
    return (
        sc.module_body()
        .resource(
            "drive",
            requires=("play_gate_sequence",),
            for_entities=(qubits_ref,),
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
    qubits: Annotated[sc.Input[tuple[str, ...]], _QUBIT_SERIES],
    couplers: Annotated[sc.Input[tuple[str, ...]], _COUPLER_SERIES],
) -> sc.ExperimentBody:
    call = opaque_parallel_gate_set(gates=gates, qubits=qubits, couplers=couplers)
    return sc.experiment(call).scan(GATE_DURATION, [28], unit="ns")


# %%
parallel_gate_collection = (
    {"control_qubit": "q0", "partner_qubit": "q1", "gate": "cz"},
    {"control_qubit": "q2", "partner_qubit": "q3", "gate": "cz"},
)
parallel_gate_qubits = ("q0", "q1", "q2", "q3")
parallel_gate_couplers = ("coupler-q0-q1", "coupler-q2-q3")
lab = sc.open_project(EXAMPLE_ROOT).connect()
parallel_gate_preview = lab.prepare(
    opaque_parallel_gate_template(
        gates=parallel_gate_collection,
        qubits=parallel_gate_qubits,
        couplers=parallel_gate_couplers,
    )
).preview()

# %%
opaque_collection_summary = {
    "collection_size": len(parallel_gate_collection),
    "points": parallel_gate_preview.point_count,
}
print(opaque_collection_summary)

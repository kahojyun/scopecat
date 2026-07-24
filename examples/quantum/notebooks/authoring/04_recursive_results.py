"""Compose repeated and parallel programs whose result axes follow the tree."""

from __future__ import annotations

# %%
from typing import Annotated

import scopecat as sc
from quantum_lab_demo import EXAMPLE_ROOT
from scopecat_quantum import authoring as q


@q.program(id="notebook.repeated-parallel-readout")
def repeated_parallel_readout(
    first: q.Qubit,
    second: q.Qubit,
    rounds: Annotated[int, sc.IntType(minimum=1)],
) -> q.QuantumFragment:
    """Return one shot-by-round-by-qubit result from the composition tree."""

    simultaneous_readout = q.parallel(
        q.measure(first, result="iq"),
        q.measure(second, result="iq"),
        axis="qubit",
        axis_kind="entity",
    )
    return q.repeat(simultaneous_readout, rounds, axis="round")


@sc.template
def recursive_readout_template(
    rounds: Annotated[sc.Input[int], sc.IntType(minimum=1)] = 3,
    shots: Annotated[sc.Input[int], sc.IntType(minimum=1)] = 5,
) -> sc.ExperimentBody:
    call = repeated_parallel_readout(
        first="q0",
        second="q1",
        rounds=rounds,
    ).with_shots(shots)
    return sc.experiment(call).record_product(call.results.iq)


# %%
lab = sc.open_project(EXAMPLE_ROOT).connect()
preview = lab.prepare(recursive_readout_template(rounds=3, shots=5)).preview()

# %%
recursive_result_summary = {
    "program": repeated_parallel_readout.id,
    "records": [record.id for record in preview.records],
    "points": preview.point_count,
}
print(recursive_result_summary)

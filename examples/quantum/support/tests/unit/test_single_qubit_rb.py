from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest
from scopecat import Quantity
from scopecat_quantum import GateCall
from scopecat_quantum import authoring as q

import quantum_lab_demo.workflows.single_qubit_rb as rb
from quantum_lab_demo.lab import quantum_lab_compiler

from .demo_lab_experiment_testkit import in_process_quantum_lab


def test_seeded_clifford_fragment_appends_an_exact_inverse() -> None:
    identity = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
    rotations = {
        "x90": ((1, 0, 0), (0, 0, -1), (0, 1, 0)),
        "xm90": ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
        "y90": ((0, 0, 1), (0, 1, 0), (-1, 0, 0)),
        "ym90": ((0, 0, -1), (0, 1, 0), (1, 0, 0)),
    }
    generated_sequences: set[tuple[str, ...]] = set()

    for length in (1, 4, 16):
        for seed in range(8):
            bound = q.bind(
                rb.single_qubit_rb_program,
                {"qubit": "q0", "length": length, "seed": seed},
            )
            gate_ids = tuple(
                operation.gate_id.value
                for operation in bound.verified.operations
                if isinstance(operation, GateCall)
            )
            generated_sequences.add(gate_ids)
            accumulated = identity
            for gate_id in gate_ids:
                accumulated = _compose(rotations[gate_id], accumulated)
            assert accumulated == identity
            assert {
                definition.id.value for definition in bound.gate_definitions
            } == set(gate_ids)

    assert len(generated_sequences) > 8


def test_single_qubit_rb_runs_as_one_domain_program_with_two_scan_axes(
    tmp_path: Path,
) -> None:
    compiler = quantum_lab_compiler()
    invocation = rb.single_qubit_rb_scratch(
        clifford_counts=(4, 64),
        seeds=(0, 1),
    )

    run = (
        in_process_quantum_lab(project_root=tmp_path, compiler=compiler)
        .prepare(invocation)
        .run()
    )
    dataset = run.data().measurements().dataset
    survival_by_length: dict[int, list[float]] = defaultdict(list)
    for record in dataset.records:
        survival = record.observables["survival_probability"]
        length = record.coordinates["clifford_length"]
        assert isinstance(survival, Quantity)
        assert type(length) is int
        survival_by_length[length].append(float(survival.value))

    assert run.manifest.status == "completed"
    assert dataset.dataset_schema.primary_coordinates == [
        "clifford_length",
        "rb_seed",
    ]
    assert len(dataset.records) == 4
    assert sum(survival_by_length[4]) / 2 == pytest.approx(
        0.5 + 0.48 * 0.985**4,
        abs=1 / rb.SINGLE_QUBIT_RB_SHOTS,
    )
    assert sum(survival_by_length[64]) / 2 == pytest.approx(
        0.5 + 0.48 * 0.985**64,
        abs=1 / rb.SINGLE_QUBIT_RB_SHOTS,
    )
    assert min(survival_by_length[4]) > max(survival_by_length[64])

    [evidence] = compiler.trace.preparations(rb.single_qubit_rb_program.id)
    assert len(evidence.points) == len(evidence.entries) == 4
    assert compiler.trace.physical_execution_count == 1


def _compose(
    after: tuple[tuple[int, ...], ...],
    before: tuple[tuple[int, ...], ...],
) -> tuple[tuple[int, ...], ...]:
    return tuple(
        tuple(
            sum(after[row][inner] * before[inner][column] for inner in range(3))
            for column in range(3)
        )
        for row in range(3)
    )

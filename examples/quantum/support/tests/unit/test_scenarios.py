from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity

from quantum_lab_demo.scenarios.opaque_collection import (
    GATE_DURATION,
    PARALLEL_GATE_SET_TEMPLATE_ID,
    ParallelGateSetProgram,
    build_parallel_gate_set_program,
    parallel_gate_set_template,
    render_parallel_gate_coupler_waveforms,
    render_parallel_gate_drive_waveforms,
)

from .demo_lab_experiment_testkit import (
    link_invocation,
    load_experiment_config,
    measurement_projection_and_points,
)


def test_scenario_template_ids() -> None:
    assert parallel_gate_set_template.definition.id == PARALLEL_GATE_SET_TEMPLATE_ID


def test_opaque_collection_scenario_resolves_and_projects() -> None:
    invocation = parallel_gate_set_template.bind().scan(
        GATE_DURATION,
        [28],
        unit="ns",
    )
    config = load_experiment_config()
    resolved = link_invocation(invocation, config_profile=config)
    projection, points = measurement_projection_and_points(invocation, config=config)

    assert resolved.program.id == PARALLEL_GATE_SET_TEMPLATE_ID
    assert resolved.program.kind == "parallel_gate_set"
    assert projection.schema_for(points) is not None


def test_parallel_gate_set_renders_disjoint_pairs() -> None:
    gates = (
        {"control_qubit": "q0", "partner_qubit": "q1", "gate": "cz"},
        {"control_qubit": "q2", "partner_qubit": "q3", "gate": "cz"},
    )
    program = _build_test_program(
        gates,
        tuple(reversed(_gate_parameter_rows(gates))),
    )

    drive_payload = render_parallel_gate_drive_waveforms(program=program)
    coupler_payload = render_parallel_gate_coupler_waveforms(program=program)

    assert len(program.gates) == 2
    assert drive_payload.entity_ids == ("q0", "q1", "q2", "q3")
    assert drive_payload.samples.shape == (4, 28)
    assert coupler_payload.entity_ids == ("coupler-q0-q1", "coupler-q2-q3")
    assert coupler_payload.samples.shape == (2, 28)


@pytest.mark.parametrize("gate_count", (1, 3))
def test_parallel_gate_compute_accepts_arbitrary_table_cardinality(
    gate_count: int,
) -> None:
    rows = [
        {
            "control_qubit": f"q{2 * index}",
            "partner_qubit": f"q{2 * index + 1}",
            "gate": "cz",
        }
        for index in range(gate_count)
    ]

    program = _build_test_program(
        rows,
        tuple(
            {
                **row,
                "coupler": f"coupler-{index}",
                "coupler_parking_flux": Quantity(
                    value=0.02 + index * 0.001,
                    unit="arb",
                ),
            }
            for index, row in enumerate(rows)
        ),
    )

    assert len(program.gates) == gate_count
    assert [gate.control_qubit for gate in program.gates] == [
        f"q{2 * index}" for index in range(gate_count)
    ]


@pytest.mark.parametrize(
    ("gates", "expected_qubits"),
    (
        pytest.param(
            ({"control_qubit": "q0", "partner_qubit": "q1"},),
            ("q0", "q1"),
            id="one-row",
        ),
        pytest.param(
            (
                {"control_qubit": "q2", "partner_qubit": "q3"},
                {"control_qubit": "q0", "partner_qubit": "q1"},
            ),
            ("q2", "q3", "q0", "q1"),
            id="reordered-two-rows",
        ),
    ),
)
def test_rendering_preserves_collection_cardinality_and_order(
    gates: tuple[dict[str, str], ...],
    expected_qubits: tuple[str, ...],
) -> None:
    gate_rows = tuple({**gate, "gate": "cz"} for gate in gates)
    program = _build_test_program(
        gate_rows,
        _gate_parameter_rows(gate_rows),
    )

    drive_payload = render_parallel_gate_drive_waveforms(program=program)
    coupler_payload = render_parallel_gate_coupler_waveforms(program=program)

    assert drive_payload.entity_ids == expected_qubits
    assert coupler_payload.entity_ids == tuple(
        f"coupler-{control}-{partner}"
        for control, partner in zip(
            expected_qubits[::2],
            expected_qubits[1::2],
            strict=True,
        )
    )
    assert drive_payload.samples.shape == (len(expected_qubits), 28)
    assert coupler_payload.samples.shape == (len(expected_qubits) // 2, 28)


def test_parallel_gate_compute_rejects_a_divergent_routing_footprint() -> None:
    gates = ({"control_qubit": "q0", "partner_qubit": "q1", "gate": "cz"},)

    with pytest.raises(ValueError, match="coupler footprint"):
        build_parallel_gate_set_program(
            gates=gates,
            gate_parameters=_gate_parameter_rows(gates),
            gate_duration=Quantity(28, "ns"),
            qubits=("q0", "q1"),
            couplers=("coupler-q2-q3",),
        )


def _build_test_program(
    gates: Sequence[Mapping[str, object]],
    gate_parameters: Sequence[Mapping[str, object]],
) -> ParallelGateSetProgram:
    return build_parallel_gate_set_program(
        gates=gates,
        gate_parameters=gate_parameters,
        gate_duration=Quantity(28, "ns"),
        qubits=tuple(
            row[column]
            for row in gates
            for column in ("control_qubit", "partner_qubit")
        ),
        couplers=tuple(row["coupler"] for row in gate_parameters),
    )


def _gate_parameter_rows(
    gates: tuple[dict[str, str], ...],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            **gate,
            "control_qubit": EntityRef(
                id=gate["control_qubit"],
                kind="logical_qubit",
            ),
            "partner_qubit": EntityRef(
                id=gate["partner_qubit"],
                kind="logical_qubit",
            ),
            "coupler": EntityRef(
                id=f"coupler-{gate['control_qubit']}-{gate['partner_qubit']}",
                kind="logical_coupler",
            ),
            "coupler_parking_flux": Quantity(0.02, "arb"),
        }
        for gate in gates
    )

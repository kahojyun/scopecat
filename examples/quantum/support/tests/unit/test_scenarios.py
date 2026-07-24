from __future__ import annotations

from pathlib import Path

import pytest
from scopecat.authoring import ExperimentInvocation
from scopecat.execution.observation import RuntimePayloadObservation
from scopecat.planning.authoring import resolve_experiment
from scopecat.records.artifact import CommandPayload
from scopecat.records.parameter import Quantity

from quantum_lab_demo.scenarios.opaque_collection import (
    GATE_DURATION,
    PARALLEL_GATE_SET_TEMPLATE_ID,
    ParallelGateSetProgram,
    RenderedWaveformBundle,
    build_parallel_gate_set_program,
    parallel_gate_set_template,
)

from .demo_lab_experiment_testkit import (
    in_process_quantum_lab,
    load_experiment_config,
    measurement_projection_and_points,
)


def test_scenario_template_ids() -> None:
    assert parallel_gate_set_template.id == PARALLEL_GATE_SET_TEMPLATE_ID


def test_opaque_collection_scenario_resolves_and_projects() -> None:
    invocation = parallel_gate_set_template.bind().scan(
        GATE_DURATION,
        [28],
        unit="ns",
    )
    config = load_experiment_config()
    resolved = resolve_experiment(invocation, config_profile=config)
    projection, points = measurement_projection_and_points(invocation, config=config)

    assert resolved.template_id == PARALLEL_GATE_SET_TEMPLATE_ID
    assert resolved.experiment.kind == "parallel_gate_set"
    assert projection.schema_for(points) is not None


def test_parallel_gate_set_renders_disjoint_pairs(tmp_path: Path) -> None:
    payloads = _run_observed_payloads(
        tmp_path,
        parallel_gate_set_template.bind().scan(GATE_DURATION, [28], unit="ns"),
    )
    gate_program = next(
        payload.payload
        for payload in payloads
        if isinstance(payload.payload, ParallelGateSetProgram)
    )
    waveform_payloads = [
        payload.payload
        for payload in payloads
        if isinstance(payload.payload, RenderedWaveformBundle)
    ]
    drive_payload = next(
        payload
        for payload in waveform_payloads
        if payload.entity_ids == ("q0", "q1", "q2", "q3")
    )
    coupler_payload = next(
        payload
        for payload in waveform_payloads
        if payload.entity_ids == ("coupler-q0-q1", "coupler-q2-q3")
    )

    assert len(gate_program.gates) == 2
    assert drive_payload.samples.shape == (4, 28)
    assert coupler_payload.samples.shape == (2, 28)


@pytest.mark.parametrize("gate_count", (1, 3))
def test_parallel_gate_compute_accepts_arbitrary_table_cardinality(
    gate_count: int,
) -> None:
    rows = [
        {
            "control_qubit": f"q{2 * index}",
            "partner_qubit": f"q{2 * index + 1}",
            "coupler": f"coupler-{index}",
            "coupler_parking_flux": Quantity(value=0.02 + index * 0.001, unit="arb"),
            "control_frequency": Quantity(value=5.0 + index * 0.1, unit="GHz"),
            "partner_frequency": Quantity(value=5.05 + index * 0.1, unit="GHz"),
        }
        for index in range(gate_count)
    ]

    program = build_parallel_gate_set_program(
        gates=rows,
        gate_duration=Quantity(value=28.0, unit="ns"),
    )

    assert len(program.gates) == gate_count
    assert [gate.control_qubit for gate in program.gates] == [
        f"q{2 * index}" for index in range(gate_count)
    ]


@pytest.mark.parametrize(
    ("gates", "expected_qubits", "expected_couplers"),
    (
        pytest.param(
            ({"control_qubit": "q0", "partner_qubit": "q1", "gate": "cz"},),
            ("q0", "q1"),
            ("coupler-q0-q1",),
            id="one-row",
        ),
        pytest.param(
            (
                {"control_qubit": "q2", "partner_qubit": "q3", "gate": "cz"},
                {"control_qubit": "q0", "partner_qubit": "q1", "gate": "cz"},
            ),
            ("q2", "q3", "q0", "q1"),
            ("coupler-q2-q3", "coupler-q0-q1"),
            id="reordered-two-rows",
        ),
    ),
)
def test_escape_hatch_preserves_collection_cardinality_and_order(
    tmp_path: Path,
    gates: tuple[dict[str, str], ...],
    expected_qubits: tuple[str, ...],
    expected_couplers: tuple[str, ...],
) -> None:
    payloads = _run_observed_payloads(
        tmp_path,
        parallel_gate_set_template.bind(gates=gates).scan(
            GATE_DURATION,
            [28],
            unit="ns",
        ),
    )
    gate_program = next(
        payload.payload
        for payload in payloads
        if isinstance(payload.payload, ParallelGateSetProgram)
    )
    waveform_payloads = [
        payload.payload
        for payload in payloads
        if isinstance(payload.payload, RenderedWaveformBundle)
    ]
    drive_payload = next(
        payload
        for payload in waveform_payloads
        if payload.entity_ids == expected_qubits
    )
    coupler_payload = next(
        payload
        for payload in waveform_payloads
        if payload.entity_ids == expected_couplers
    )

    assert [
        (gate.control_qubit, gate.partner_qubit, gate.coupler)
        for gate in gate_program.gates
    ] == [
        (control, partner, coupler)
        for (control, partner), coupler in zip(
            zip(expected_qubits[::2], expected_qubits[1::2], strict=True),
            expected_couplers,
            strict=True,
        )
    ]
    assert drive_payload.samples.shape == (len(expected_qubits), 28)
    assert coupler_payload.samples.shape == (len(expected_couplers), 28)


def _run_observed_payloads(
    tmp_path: Path,
    invocation: ExperimentInvocation,
) -> list[CommandPayload]:
    observations: list[RuntimePayloadObservation] = []
    in_process_quantum_lab(project_root=tmp_path).prepare(invocation).run(
        payload_observer=observations.append,
    )
    return [observation.payload for observation in observations]

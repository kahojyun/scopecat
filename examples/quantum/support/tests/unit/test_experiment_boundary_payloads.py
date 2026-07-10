from __future__ import annotations

from pathlib import Path

from demo_lab_experiment_testkit import load_experiment_config
from scopecat.authoring import ExperimentInvocation, resolve_experiment
from scopecat.experiments import (
    ExperimentSpec,
)
from scopecat.instruments import PayloadRef, RuntimePayloadObservation
from scopecat.models.artifact import CommandPayload

from quantum_lab_demo.experiments import SQG_RB_TEMPLATE
from quantum_lab_demo.experiments.payloads import (
    RandomizedBenchmarkingPulseBundle,
    RandomizedBenchmarkingSequence,
)
from quantum_lab_demo.lab import quantum_lab


def test_sequence_compilation_stays_memory_payload_boundary(
    tmp_path: Path,
) -> None:
    invocation = SQG_RB_TEMPLATE.bind(qubit="q0", seed=11).scan(
        "clifford_count",
        [4, 8],
    )
    resolved = resolve_experiment(
        invocation,
        workspace=tmp_path,
        config_profile=load_experiment_config(),
    )
    assert isinstance(resolved.experiment, ExperimentSpec)
    preview = (
        quantum_lab(
            workspace=tmp_path,
            config_profile=load_experiment_config(),
        )
        .prepare(invocation)
        .preview()
    )
    payloads = _run_observed_payloads(tmp_path, invocation)

    assert [point.coordinates["clifford_count"] for point in preview.points] == [
        4,
        8,
    ]
    assert [
        (field.resource_id, field.capability_id, field.field_path)
        for field in preview.state_fields
        if isinstance(field.value, PayloadRef)
    ] == [
        ("drive-stack", "play_gate_sequence", "sequence"),
        ("drive-stack", "play_pulse_program", "program"),
        ("drive-stack", "play_gate_sequence", "sequence"),
        ("drive-stack", "play_pulse_program", "program"),
    ]
    assert [payload.schema_id for payload in payloads] == [
        "gate_sequence",
        "pulse_program",
        "gate_sequence",
        "pulse_program",
    ]
    payload_values = [payload.payload for payload in payloads]
    assert (
        sum(
            isinstance(payload, RandomizedBenchmarkingSequence)
            for payload in payload_values
        )
        == 2
    )
    assert (
        sum(
            isinstance(payload, RandomizedBenchmarkingPulseBundle)
            for payload in payload_values
        )
        == 2
    )


def _run_observed_payloads(
    tmp_path: Path,
    invocation: ExperimentInvocation,
) -> list[CommandPayload]:
    observations: list[RuntimePayloadObservation] = []
    quantum_lab(workspace=tmp_path).prepare(invocation).run(
        payload_observer=observations.append,
    )
    return [observation.payload for observation in observations]

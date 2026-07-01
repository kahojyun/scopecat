from __future__ import annotations

from pathlib import Path

from demo_lab_sample_testkit import load_sample_config, sample_parameter_build
from scopecat.authoring import resolve_experiment
from scopecat.experiments import (
    ExperimentSpec,
    plan_experiment,
)
from scopecat.models.parameter import Quantity

from quantum_lab_demo.sample import sqg_rb


def test_sample_sequence_compilation_stays_domain_asset_boundary(
    tmp_path: Path,
) -> None:
    resolved = resolve_experiment(
        sqg_rb(qubit="q0", lengths=[4, 8], seed=11),
        workspace=tmp_path,
        config_profile=load_sample_config(),
    )
    assert isinstance(resolved.experiment, ExperimentSpec)

    plan = plan_experiment(resolved.experiment, sample_parameter_build())

    assert [(asset.id, asset.kind, asset.media_type) for asset in plan.assets] == [
        (
            "q0-sqg-rb-sequence",
            "gate_sequence",
            "application/vnd.scopecat.opaque+json",
        ),
        (
            "q0-sqg-rb-pulsedict",
            "pulse_program",
            "application/vnd.scopecat.opaque+json",
        ),
    ]
    assert [(asset.uri, asset.path, asset.content_hash) for asset in plan.assets] == [
        ("scopecat-asset:q0-sqg-rb-sequence", None, None),
        ("scopecat-asset:q0-sqg-rb-pulsedict", None, None),
    ]
    assert [point.row["clifford_count"] for point in plan.points] == [
        Quantity(value=4, unit="count"),
        Quantity(value=8, unit="count"),
    ]
    assert [
        (record.resource, record.field, record.value)
        for record in plan.desired_state
        if isinstance(record.value, dict)
    ] == [
        (
            "drive-stack",
            "play_gate_sequence.sequence",
            {"kind": "asset", "asset_id": "q0-sqg-rb-sequence"},
        ),
        (
            "drive-stack",
            "play_pulse_program.program",
            {"kind": "asset", "asset_id": "q0-sqg-rb-pulsedict"},
        ),
        (
            "drive-stack",
            "play_gate_sequence.sequence",
            {"kind": "asset", "asset_id": "q0-sqg-rb-sequence"},
        ),
        (
            "drive-stack",
            "play_pulse_program.program",
            {"kind": "asset", "asset_id": "q0-sqg-rb-pulsedict"},
        ),
    ]

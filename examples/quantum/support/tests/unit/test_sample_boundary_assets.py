from __future__ import annotations

from pathlib import Path

from demo_lab_sample_testkit import load_sample_config, sample_parameter_build
from scopecat.authoring import resolve_experiment
from scopecat.experiments import (
    ExperimentSpec,
    acquire,
    experiment,
    plan_experiment,
    set_state,
)
from scopecat.models.artifact import ArtifactRef
from scopecat.models.parameter import Quantity
from scopecat.relations import grid

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
    plan_json = plan.model_dump_json()
    assert "waveform" not in plan_json
    assert "samples" not in plan_json
    assert "compiled_sequence" not in plan_json


def test_feedback_and_active_reset_stay_domain_program_assets() -> None:
    feedback = ArtifactRef(
        id="q0-feedback-decoder",
        kind="feedback_program",
        uri="scopecat-asset:q0-feedback-decoder",
        media_type="application/vnd.scopecat.opaque+json",
    )
    active_reset = ArtifactRef(
        id="q0-active-reset",
        kind="active_reset_program",
        uri="scopecat-asset:q0-active-reset",
        media_type="application/vnd.scopecat.opaque+json",
    )
    spec = experiment(
        id="sample-feedback-active-reset",
        kind="sample_feedback_active_reset",
        points=grid(cycle=[0, 1]),
        state=[
            set_state(
                "control-stack",
                "feedback.program",
                {"kind": "asset", "asset_id": feedback.id},
            ),
            set_state(
                "control-stack",
                "active_reset.program",
                {"kind": "asset", "asset_id": active_reset.id},
            ),
        ],
        assets=[feedback, active_reset],
        acquire=acquire("iq"),
    )

    plan = plan_experiment(spec, sample_parameter_build())

    assert [(asset.id, asset.kind) for asset in plan.assets] == [
        ("q0-feedback-decoder", "feedback_program"),
        ("q0-active-reset", "active_reset_program"),
    ]
    assert [
        (record.point_id, record.resource, record.field, record.value)
        for record in plan.desired_state
    ] == [
        (
            0,
            "control-stack",
            "feedback.program",
            {"kind": "asset", "asset_id": "q0-feedback-decoder"},
        ),
        (
            0,
            "control-stack",
            "active_reset.program",
            {"kind": "asset", "asset_id": "q0-active-reset"},
        ),
        (
            1,
            "control-stack",
            "feedback.program",
            {"kind": "asset", "asset_id": "q0-feedback-decoder"},
        ),
        (
            1,
            "control-stack",
            "active_reset.program",
            {"kind": "asset", "asset_id": "q0-active-reset"},
        ),
    ]
    assert plan.diagnostics == []


def test_acquisition_correction_and_restore_stay_boundary_assets() -> None:
    gate = ArtifactRef(
        id="q0-acquisition-gate",
        kind="acquisition_gate_program",
        uri="scopecat-asset:q0-acquisition-gate",
        media_type="application/vnd.scopecat.opaque+json",
    )
    dac_upload = ArtifactRef(
        id="q0-dac-upload-correction",
        kind="dac_upload_correction",
        uri="scopecat-asset:q0-dac-upload-correction",
        media_type="application/vnd.scopecat.opaque+json",
    )
    crosstalk = ArtifactRef(
        id="q0-crosstalk-correction",
        kind="crosstalk_correction",
        uri="scopecat-asset:q0-crosstalk-correction",
        media_type="application/vnd.scopecat.opaque+json",
    )
    spec = experiment(
        id="sample-acquisition-correction-boundary",
        kind="sample_boundary_controls",
        points=grid(point_id=[0]),
        state=[
            set_state(
                "acquisition-stack",
                "acquisition_gate.program",
                {"kind": "asset", "asset_id": gate.id},
            ),
            set_state(
                "drive-stack",
                "dac_upload.correction",
                {"kind": "asset", "asset_id": dac_upload.id},
            ),
            set_state(
                "drive-stack",
                "crosstalk.correction",
                {"kind": "asset", "asset_id": crosstalk.id},
            ),
            set_state("drive-stack", "scoped_restore.policy", "after_point"),
        ],
        assets=[gate, dac_upload, crosstalk],
        acquire=acquire("iq"),
    )

    plan = plan_experiment(spec, sample_parameter_build())

    assert [(asset.id, asset.kind) for asset in plan.assets] == [
        ("q0-acquisition-gate", "acquisition_gate_program"),
        ("q0-dac-upload-correction", "dac_upload_correction"),
        ("q0-crosstalk-correction", "crosstalk_correction"),
    ]
    assert [
        (record.resource, record.field, record.value) for record in plan.desired_state
    ] == [
        (
            "acquisition-stack",
            "acquisition_gate.program",
            {"kind": "asset", "asset_id": "q0-acquisition-gate"},
        ),
        (
            "drive-stack",
            "dac_upload.correction",
            {"kind": "asset", "asset_id": "q0-dac-upload-correction"},
        ),
        (
            "drive-stack",
            "crosstalk.correction",
            {"kind": "asset", "asset_id": "q0-crosstalk-correction"},
        ),
        ("drive-stack", "scoped_restore.policy", "after_point"),
    ]
    assert plan.diagnostics == []

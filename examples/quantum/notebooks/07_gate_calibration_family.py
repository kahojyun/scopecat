"""Notebook-style example: gate calibration family."""

from __future__ import annotations

# %%
from typing import Any

import scopecat as sc
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.experiments import (
    CZ_CHEVRON_TEMPLATE,
    CZ_RB_TEMPLATE,
    FLUX_BACKGROUND_RABI_TEMPLATE,
    PARALLEL_GATE_SET_TEMPLATE,
    RABI_TEMPLATE,
    SIMULTANEOUS_RABI_TEMPLATE,
    SPECTATOR_CZ_TEMPLATE,
    SYSTEM_BACKGROUND_RABI_TEMPLATE,
)

# %%
workspace = notebook_workspace("07-gate-calibration-family")
lab = quantum_lab(workspace=workspace)

# %%
rabi_preview = (
    lab.prepare(RABI_TEMPLATE)
    .input("qubit", "q0")
    .scan("drive_length", span=sc.Quantity(value=60.0, unit="ns"), points=7)
    .preview(
        name="gate family rabi length scan",
        tags=("gate", "rabi"),
        description="single-qubit scan with a template scan override",
    )
)

# %%
rabi_qubit_scan_preview = (
    lab.prepare(RABI_TEMPLATE)
    .scan("qubit", ["q0", "q1"])
    .preview(
        name="gate family rabi qubit scan",
        tags=("gate", "rabi", "runtime-scan"),
        description=("scan the template qubit input without defining another template"),
    )
)

# %%
simultaneous_rabi_preview = (
    lab.prepare(SIMULTANEOUS_RABI_TEMPLATE)
    .scan("drive_length", span=sc.Quantity(value=40.0, unit="ns"), points=5)
    .preview(
        name="gate family simultaneous rabi",
        tags=("gate", "rabi", "simultaneous"),
        description="multi-qubit drive program returning one complex array observable",
    )
)

# %%
flux_background_preview = (
    lab.prepare(FLUX_BACKGROUND_RABI_TEMPLATE)
    .inputs(
        qubit="q0",
        coupler="coupler-q0-q1",
        flux_bias=sc.Quantity(value=0.05, unit="arb"),
    )
    .preview(
        name="gate family rabi with flux background",
        tags=("gate", "rabi", "background"),
        description="the same Rabi shape combined with a reusable background module",
    )
)

# %%
system_background_preview = (
    lab.prepare(SYSTEM_BACKGROUND_RABI_TEMPLATE)
    .input("qubit", "q0")
    .preview(
        name="gate family rabi with parameter-table background",
        tags=("gate", "rabi", "background", "parameters"),
        description="materialize all coupler parking outputs from accepted parameters",
    )
)

# %%
cz_rb_preview = (
    lab.prepare(CZ_RB_TEMPLATE)
    .inputs(
        control_qubit="q0",
        partner_qubit="q1",
        coupler="coupler-q0-q1",
        seed=23,
    )
    .scan("clifford_count", [2, 4, 8], unit="count")
    .preview(
        name="gate family CZ RB",
        tags=("gate", "benchmarking"),
        description=(
            "two-qubit gate experiment using drive, coupler, and readout modules"
        ),
    )
)

# %%
cz_chevron_preview = (
    lab.prepare(CZ_CHEVRON_TEMPLATE)
    .inputs(control_qubit="q0", partner_qubit="q1", coupler="coupler-q0-q1")
    .scan("coupler_duration", [24, 36], unit="ns")
    .scan("coupler_amplitude", [0.18, 0.24], unit="arb")
    .preview(
        name="gate family CZ chevron",
        tags=("gate", "chevron"),
        description="template-level amplitude-duration defaults for CZ calibration",
    )
)

# %%
runtime_parameter_scan_preview = (
    lab.prepare(CZ_CHEVRON_TEMPLATE)
    .inputs(control_qubit="q0", partner_qubit="q1", coupler="coupler-q0-q1")
    .scan("coupler_duration", [24], unit="ns")
    .scan("coupler_amplitude", [0.18], unit="arb")
    .scan(
        sc.param_axis(
            sc.param_row(
                "two_qubit_gates",
                control_qubit=sc.input("control_qubit"),
                partner_qubit=sc.input("partner_qubit"),
                gate="cz",
            ),
            "coupler_parking_flux",
            [0.02, 0.04],
            axis_id="parking_flux",
            unit="arb",
        )
    )
    .preview(
        name="gate family CZ parking-flux scan",
        tags=("gate", "chevron", "runtime-scan"),
        description=(
            "add a point-local parameter scan without defining another template"
        ),
    )
)

# %%
spectator_cz_preview = (
    lab.prepare(SPECTATOR_CZ_TEMPLATE)
    .inputs(
        control_qubit="q0",
        partner_qubit="q1",
        coupler="coupler-q0-q1",
        background_couplers=sc.entity_array(("coupler-q2-q3",)),
    )
    .scan("coupler_duration", [24], unit="ns")
    .scan("coupler_amplitude", [0.18], unit="arb")
    .preview(
        name="gate family spectator-aware CZ",
        tags=("gate", "spectator"),
        description=(
            "foreground CZ calibration with explicit spectator background state"
        ),
    )
)

# %%
parallel_gate_preview = (
    lab.prepare(PARALLEL_GATE_SET_TEMPLATE)
    .scan("gate_duration", [28], unit="ns")
    .preview(
        name="gate family parallel gate set",
        tags=("gate", "parallel"),
        description=(
            "two disjoint CZ gates sharing drive, coupler, and readout resources"
        ),
    )
)

# %%
waveform_plan = (
    lab.prepare(CZ_CHEVRON_TEMPLATE)
    .inputs(control_qubit="q0", partner_qubit="q1", coupler="coupler-q0-q1")
    .scan("coupler_duration", [24], unit="ns")
    .scan("coupler_amplitude", [0.18], unit="arb")
)
waveform_preview = waveform_plan.preview(
    name="gate family waveform compute",
    tags=("gate", "waveform", "compute"),
    description="one CZ point rendered into route-aware in-memory waveform payloads",
)

# %%
events: list[dict[str, Any]] = []
waveform_run = waveform_plan.run(
    name="gate family waveform compute",
    tags=("gate", "waveform", "compute"),
    description="record runtime compute summaries without persisting waveform payloads",
    event_sink=lambda event: events.append(event.model_dump(mode="python")),
)

# %%
compute_events = [event for event in events if event["kind"] == "compute_finished"]
waveform_summaries = [
    event["summary"]
    for event in compute_events
    if event["summary"].get("payload_kind") == "pulse_program"
]
build_preview = next(
    payload
    for payload in waveform_preview.payloads
    if payload.node_id == "build-cz-chevron-program"
)
drive_event = next(
    event
    for event in compute_events
    if event["summary"].get("node_id") == "render-cz-chevron-drive-waveforms"
)

flux_background_state_count = len(
    {
        (field.resource_id, field.capability_id, field.field_path)
        for field in flux_background_preview.state_fields
        if field.capability_id == "set_flux_bias" and field.field_path == "offset"
    }
)
system_background_state_channel_entries = sorted(
    {
        (
            field.resource_id,
            field.capability_id,
            field.field_path,
            tuple(
                (binding.entity_id, binding.channel_id)
                for binding in field.channel_bindings
            ),
        )
        for field in system_background_preview.state_fields
        if field.resource_id == "coupler-stack"
        and field.capability_id == "set_flux_bias"
    }
)
system_background_state_channels = [
    (
        resource_id,
        capability_id,
        field_path,
        list(channel_bindings),
    )
    for (
        resource_id,
        capability_id,
        field_path,
        channel_bindings,
    ) in system_background_state_channel_entries
]

# %%
gate_family_summary = {
    "rabi_points": rabi_preview.point_count,
    "rabi_qubit_scan_points": rabi_qubit_scan_preview.point_count,
    "rabi_qubit_scan_coordinates": list(rabi_qubit_scan_preview.coordinate_ids),
    "simultaneous_rabi_points": simultaneous_rabi_preview.point_count,
    "flux_background_state_count": flux_background_state_count,
    "system_background_state_channels": system_background_state_channels,
    "cz_rb_points": cz_rb_preview.point_count,
    "cz_chevron_points": cz_chevron_preview.point_count,
    "runtime_scan_points": runtime_parameter_scan_preview.point_count,
    "runtime_scan_coordinates": list(runtime_parameter_scan_preview.coordinate_ids),
    "spectator_cz_points": spectator_cz_preview.point_count,
    "parallel_gate_points": parallel_gate_preview.point_count,
    "waveform_preview_payloads": [
        (payload.node_id, payload.kind, payload.state_fields)
        for payload in waveform_preview.payloads
    ],
    "waveform_build_dependencies": build_preview.dependencies,
    "waveform_drive_runtime_dependencies": drive_event["summary"].get("dependencies"),
    "waveform_run_status": waveform_run.manifest.status,
    "waveform_compute_event_count": len(compute_events),
    "waveform_shapes": [summary.get("sample_shape") for summary in waveform_summaries],
    "waveform_channels": [
        summary.get("channel_count") for summary in waveform_summaries
    ],
}
print(gate_family_summary)

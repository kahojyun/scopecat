"""Notebook-style example: gate calibration family."""

from __future__ import annotations

# %%
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
from quantum_lab_demo.experiments.points import (
    CLIFFORD_COUNT,
    COUPLER_AMPLITUDE,
    COUPLER_DURATION,
    COUPLER_PARKING_FLUX,
    DRIVE_LENGTH,
    GATE_DURATION,
    QUBIT,
)

# %%
workspace = notebook_workspace("07-gate-calibration-family")
lab = quantum_lab(workspace=workspace)

# %%
rabi_preview = (
    lab.prepare(RABI_TEMPLATE)
    .input("qubit", "q0")
    .scan(DRIVE_LENGTH, span=sc.Quantity(value=60.0, unit="ns"), points=7)
    .preview(
        name="gate family rabi length scan",
        tags=("gate", "rabi"),
        description="single-qubit scan with a template scan override",
    )
)

# %%
rabi_qubit_scan_preview = (
    lab.prepare(RABI_TEMPLATE)
    .scan(QUBIT, ["q0", "q1"])
    .preview(
        name="gate family rabi qubit scan",
        tags=("gate", "rabi", "runtime-scan"),
        description=("scan the template qubit input without defining another template"),
    )
)

# %%
simultaneous_rabi_preview = (
    lab.prepare(SIMULTANEOUS_RABI_TEMPLATE)
    .scan(DRIVE_LENGTH, span=sc.Quantity(value=40.0, unit="ns"), points=5)
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
    .scan(CLIFFORD_COUNT, [2, 4, 8])
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
    .scan(COUPLER_DURATION, [24, 36], unit="ns")
    .scan(COUPLER_AMPLITUDE, [0.18, 0.24], unit="arb")
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
    .scan(COUPLER_DURATION, [24], unit="ns")
    .scan(COUPLER_AMPLITUDE, [0.18], unit="arb")
    .scan(
        sc.param_axis(
            COUPLER_PARKING_FLUX,
            sc.param_row(
                "two_qubit_gates",
                control_qubit=sc.input(
                    "control_qubit",
                    sc.ScalarType(sc.EntityType(entity_kind="logical_qubit")),
                ),
                partner_qubit=sc.input(
                    "partner_qubit",
                    sc.ScalarType(sc.EntityType(entity_kind="logical_qubit")),
                ),
                gate="cz",
            ),
            "coupler_parking_flux",
            [0.02, 0.04],
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
        background_couplers=("coupler-q2-q3",),
    )
    .scan(COUPLER_DURATION, [24], unit="ns")
    .scan(COUPLER_AMPLITUDE, [0.18], unit="arb")
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
    .scan(GATE_DURATION, [28], unit="ns")
    .preview(
        name="gate family parallel gate set",
        tags=("gate", "parallel"),
        description=(
            "two disjoint CZ gates sharing drive, coupler, and readout resources"
        ),
    )
)

# %%
gate_family_summary = {
    "rabi_points": rabi_preview.point_count,
    "rabi_qubit_scan_points": rabi_qubit_scan_preview.point_count,
    "rabi_qubit_scan_coordinates": list(rabi_qubit_scan_preview.coordinate_ids),
    "simultaneous_rabi_points": simultaneous_rabi_preview.point_count,
    "flux_background_records": [
        record.id for record in flux_background_preview.records
    ],
    "system_background_records": [
        record.id for record in system_background_preview.records
    ],
    "cz_rb_points": cz_rb_preview.point_count,
    "cz_chevron_points": cz_chevron_preview.point_count,
    "runtime_scan_points": runtime_parameter_scan_preview.point_count,
    "runtime_scan_coordinates": list(runtime_parameter_scan_preview.coordinate_ids),
    "spectator_cz_points": spectator_cz_preview.point_count,
    "parallel_gate_points": parallel_gate_preview.point_count,
}
print(gate_family_summary)

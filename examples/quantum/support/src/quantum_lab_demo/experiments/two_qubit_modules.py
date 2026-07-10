"""two-qubit gate modules."""

from __future__ import annotations

import scopecat as sc

from quantum_lab_demo.experiments.compute import (
    build_cz_chevron_program,
    build_parallel_gate_set_program,
    render_cz_coupler_waveforms,
    render_cz_drive_waveforms,
    render_parallel_gate_coupler_waveforms,
    render_parallel_gate_drive_waveforms,
)
from quantum_lab_demo.experiments.ids import (
    CZ_CHEVRON_TEMPLATE_ID,
    PARALLEL_GATE_SET_TEMPLATE_ID,
    QUBIT_PARAMETER_TABLE,
    TWO_QUBIT_GATE_PARAMETER_TABLE,
)
from quantum_lab_demo.experiments.parameter_refs import (
    qubit_param,
    two_qubit_gate_param,
)

CZ_CHEVRON_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.two_qubit.cz_chevron",
        metadata={"template_id": CZ_CHEVRON_TEMPLATE_ID},
    )
    .entity_inputs_from("control_qubit", "partner_qubit", "coupler")
    .input("coupler_duration", value_type=sc.ScalarType(sc.QuantityType()))
    .input("coupler_amplitude", value_type=sc.ScalarType(sc.QuantityType()))
    .resource(
        "drive",
        requires=("play_gate_sequence", "play_pulse_program"),
        for_entities=("control_qubit", "partner_qubit"),
    )
    .resource(
        "coupler",
        requires=("play_coupler_pulse",),
        for_entities=("coupler",),
    )
    .compute(
        "build-cz-chevron-program",
        fn=build_cz_chevron_program,
        output_type=sc.ScalarType(sc.PayloadType("gate_sequence")),
        inputs={
            "control_qubit": sc.input("control_qubit"),
            "partner_qubit": sc.input("partner_qubit"),
            "coupler": sc.input("coupler"),
            "duration": sc.var("coupler_duration"),
            "amplitude": sc.var("coupler_amplitude"),
            "control_echo_amplitude": two_qubit_gate_param("control_echo_amplitude"),
            "partner_echo_amplitude": two_qubit_gate_param("partner_echo_amplitude"),
            "coupler_parking_flux": two_qubit_gate_param("coupler_parking_flux"),
            "sample_rate_hz": two_qubit_gate_param("sample_rate_hz"),
            "control_drive_frequency": qubit_param(
                "drive_frequency",
                input_id="control_qubit",
            ),
            "partner_drive_frequency": qubit_param(
                "drive_frequency",
                input_id="partner_qubit",
            ),
        },
    )
    .compute(
        "render-cz-chevron-drive-waveforms",
        fn=render_cz_drive_waveforms,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={
            "program": sc.compute_result("build-cz-chevron-program"),
            "drive_route": sc.route("drive"),
        },
        route_ports=("drive",),
    )
    .compute(
        "render-cz-chevron-coupler-waveforms",
        fn=render_cz_coupler_waveforms,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={
            "program": sc.compute_result("build-cz-chevron-program"),
            "coupler_route": sc.route("coupler"),
        },
        route_ports=("coupler",),
    )
    .bind(
        "drive.play_gate_sequence.sequence",
        sc.compute_result("build-cz-chevron-program"),
    )
    .bind(
        "drive.play_pulse_program.program",
        sc.compute_result("render-cz-chevron-drive-waveforms"),
    )
    .bind("drive.play_pulse_program.length", sc.var("coupler_duration"))
    .bind(
        "drive.play_pulse_program.amplitude",
        two_qubit_gate_param("control_echo_amplitude"),
    )
    .bind(
        "drive.play_pulse_program.frequency",
        qubit_param("drive_frequency", input_id="control_qubit"),
    )
    .bind(
        "coupler.play_coupler_pulse.program",
        sc.compute_result("render-cz-chevron-coupler-waveforms"),
    )
    .build()
)

PARALLEL_GATE_TABLE_TYPE = sc.TableType(
    columns=(
        sc.TableColumn("control_qubit", sc.ScalarType(sc.StringType(min_length=1))),
        sc.TableColumn("partner_qubit", sc.ScalarType(sc.StringType(min_length=1))),
        sc.TableColumn("gate", sc.ScalarType(sc.StringType(min_length=1))),
    ),
    primary_key=("control_qubit", "partner_qubit", "gate"),
    min_rows=1,
)

_PARALLEL_GATE_KEYS = sc.input_table("gates")
_PARALLEL_GATE_KEY = {
    "control_qubit": sc.col("control_qubit"),
    "partner_qubit": sc.col("partner_qubit"),
    "gate": sc.col("gate"),
}
_PARALLEL_GATES = _PARALLEL_GATE_KEYS.with_columns(
    coupler=sc.table_param(
        TWO_QUBIT_GATE_PARAMETER_TABLE,
        key=_PARALLEL_GATE_KEY,
        column="coupler",
    ),
    coupler_parking_flux=sc.table_param(
        TWO_QUBIT_GATE_PARAMETER_TABLE,
        key=_PARALLEL_GATE_KEY,
        column="coupler_parking_flux",
    ),
    control_frequency=sc.table_param(
        QUBIT_PARAMETER_TABLE,
        key={"qubit": sc.col("control_qubit")},
        column="drive_frequency",
    ),
    partner_frequency=sc.table_param(
        QUBIT_PARAMETER_TABLE,
        key={"qubit": sc.col("partner_qubit")},
        column="drive_frequency",
    ),
).select(
    "control_qubit",
    "partner_qubit",
    "coupler",
    "coupler_parking_flux",
    "control_frequency",
    "partner_frequency",
)
PARALLEL_GATE_QUBITS = _PARALLEL_GATE_KEYS.entities(
    "control_qubit",
    "partner_qubit",
)

PARALLEL_GATE_SET_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.two_qubit.parallel_gate_set",
        metadata={"template_id": PARALLEL_GATE_SET_TEMPLATE_ID},
    )
    .input("gates", value_type=PARALLEL_GATE_TABLE_TYPE)
    .input("gate_duration", value_type=sc.ScalarType(sc.QuantityType()))
    .resource(
        "drive",
        requires=("play_gate_sequence", "play_pulse_program"),
        for_entities=(PARALLEL_GATE_QUBITS,),
    )
    .resource(
        "coupler",
        requires=("play_coupler_pulse",),
        for_entities=(_PARALLEL_GATES.entities("coupler"),),
    )
    .compute(
        "build-parallel-gate-set-program",
        fn=build_parallel_gate_set_program,
        output_type=sc.ScalarType(sc.PayloadType("gate_sequence")),
        inputs={
            "gates": _PARALLEL_GATES,
            "gate_duration": sc.var("gate_duration"),
        },
    )
    .compute(
        "render-parallel-gate-drive-waveforms",
        fn=render_parallel_gate_drive_waveforms,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={
            "program": sc.compute_result("build-parallel-gate-set-program"),
            "drive_route": sc.route("drive"),
        },
        route_ports=("drive",),
    )
    .compute(
        "render-parallel-gate-coupler-waveforms",
        fn=render_parallel_gate_coupler_waveforms,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={
            "program": sc.compute_result("build-parallel-gate-set-program"),
            "coupler_route": sc.route("coupler"),
        },
        route_ports=("coupler",),
    )
    .bind(
        "drive.play_gate_sequence.sequence",
        sc.compute_result("build-parallel-gate-set-program"),
    )
    .bind(
        "drive.play_pulse_program.program",
        sc.compute_result("render-parallel-gate-drive-waveforms"),
    )
    .bind(
        "coupler.play_coupler_pulse.program",
        sc.compute_result("render-parallel-gate-coupler-waveforms"),
    )
    .build()
)

__all__ = [
    "CZ_CHEVRON_MODULE",
    "PARALLEL_GATE_QUBITS",
    "PARALLEL_GATE_SET_MODULE",
    "PARALLEL_GATE_TABLE_TYPE",
]

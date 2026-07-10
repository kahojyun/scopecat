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
from quantum_lab_demo.experiments.points import (
    COUPLER_AMPLITUDE,
    COUPLER_DURATION,
    GATE_DURATION,
)

_QUBIT = sc.ScalarType(sc.EntityType(entity_kind="logical_qubit"))
_COUPLER = sc.ScalarType(sc.EntityType(entity_kind="logical_coupler"))
_FLOAT = sc.ScalarType(sc.FloatType())
_QUANTITY = sc.ScalarType(sc.QuantityType())

_CZ_CONTROL_QUBIT = sc.input("control_qubit", _QUBIT)
_CZ_PARTNER_QUBIT = sc.input("partner_qubit", _QUBIT)
_CZ_COUPLER = sc.input("coupler", _COUPLER)


def _cz_gate_param(column: str):
    return two_qubit_gate_param(
        column,
        control_qubit=_CZ_CONTROL_QUBIT,
        partner_qubit=_CZ_PARTNER_QUBIT,
        value_type=_FLOAT if column == "sample_rate_hz" else _QUANTITY,
    )


_BUILD_CZ_CHEVRON_PROGRAM = sc.compute(
    "build-cz-chevron-program",
    fn=build_cz_chevron_program,
    output_type=sc.ScalarType(sc.PayloadType("gate_sequence")),
    inputs={
        "control_qubit": _CZ_CONTROL_QUBIT,
        "partner_qubit": _CZ_PARTNER_QUBIT,
        "coupler": _CZ_COUPLER,
        "duration": COUPLER_DURATION,
        "amplitude": COUPLER_AMPLITUDE,
        "control_echo_amplitude": _cz_gate_param("control_echo_amplitude"),
        "partner_echo_amplitude": _cz_gate_param("partner_echo_amplitude"),
        "coupler_parking_flux": _cz_gate_param("coupler_parking_flux"),
        "sample_rate_hz": _cz_gate_param("sample_rate_hz"),
        "control_drive_frequency": qubit_param(
            "drive_frequency",
            _CZ_CONTROL_QUBIT,
        ),
        "partner_drive_frequency": qubit_param(
            "drive_frequency",
            _CZ_PARTNER_QUBIT,
        ),
    },
)
_RENDER_CZ_DRIVE_WAVEFORMS = sc.compute(
    "render-cz-chevron-drive-waveforms",
    fn=render_cz_drive_waveforms,
    output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
    inputs={
        "program": _BUILD_CZ_CHEVRON_PROGRAM.output,
        "drive_route": sc.route("drive"),
    },
)
_RENDER_CZ_COUPLER_WAVEFORMS = sc.compute(
    "render-cz-chevron-coupler-waveforms",
    fn=render_cz_coupler_waveforms,
    output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
    inputs={
        "program": _BUILD_CZ_CHEVRON_PROGRAM.output,
        "coupler_route": sc.route("coupler"),
    },
)

CZ_CHEVRON_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.two_qubit.cz_chevron",
        metadata={"template_id": CZ_CHEVRON_TEMPLATE_ID},
    )
    .inputs(
        _CZ_CONTROL_QUBIT,
        _CZ_PARTNER_QUBIT,
        _CZ_COUPLER,
    )
    .resource(
        "drive",
        requires=("play_gate_sequence", "play_pulse_program"),
        for_entities=(_CZ_CONTROL_QUBIT, _CZ_PARTNER_QUBIT),
    )
    .resource(
        "coupler",
        requires=("play_coupler_pulse",),
        for_entities=(_CZ_COUPLER,),
    )
    .computes(
        _BUILD_CZ_CHEVRON_PROGRAM,
        _RENDER_CZ_DRIVE_WAVEFORMS,
        _RENDER_CZ_COUPLER_WAVEFORMS,
    )
    .bind(
        "drive.play_gate_sequence.sequence",
        _BUILD_CZ_CHEVRON_PROGRAM.output,
    )
    .bind(
        "drive.play_pulse_program.program",
        _RENDER_CZ_DRIVE_WAVEFORMS.output,
    )
    .bind("drive.play_pulse_program.length", COUPLER_DURATION)
    .bind(
        "drive.play_pulse_program.amplitude",
        _cz_gate_param("control_echo_amplitude"),
    )
    .bind(
        "drive.play_pulse_program.frequency",
        qubit_param("drive_frequency", _CZ_CONTROL_QUBIT),
    )
    .bind(
        "coupler.play_coupler_pulse.program",
        _RENDER_CZ_COUPLER_WAVEFORMS.output,
    )
    .build()
)

PARALLEL_GATE_TABLE_TYPE = sc.TableType(
    columns=(
        sc.TableColumn("control_qubit", _QUBIT),
        sc.TableColumn("partner_qubit", _QUBIT),
        sc.TableColumn("gate", sc.ScalarType(sc.StringType(min_length=1))),
    ),
    primary_key=("control_qubit", "partner_qubit", "gate"),
    min_rows=1,
)

_PARALLEL_GATE_KEYS = sc.input("gates", PARALLEL_GATE_TABLE_TYPE)
_PARALLEL_GATES = _PARALLEL_GATE_KEYS.with_columns(
    lambda row: {
        "coupler": sc.parameter_lookup(
            TWO_QUBIT_GATE_PARAMETER_TABLE,
            key={
                "control_qubit": row["control_qubit"],
                "partner_qubit": row["partner_qubit"],
                "gate": row["gate"],
            },
            column="coupler",
            value_type=_COUPLER,
        ),
        "coupler_parking_flux": sc.parameter_lookup(
            TWO_QUBIT_GATE_PARAMETER_TABLE,
            key={
                "control_qubit": row["control_qubit"],
                "partner_qubit": row["partner_qubit"],
                "gate": row["gate"],
            },
            column="coupler_parking_flux",
            value_type=_QUANTITY,
        ),
        "control_frequency": sc.parameter_lookup(
            QUBIT_PARAMETER_TABLE,
            key={"qubit": row["control_qubit"]},
            column="drive_frequency",
            value_type=_QUANTITY,
        ),
        "partner_frequency": sc.parameter_lookup(
            QUBIT_PARAMETER_TABLE,
            key={"qubit": row["partner_qubit"]},
            column="drive_frequency",
            value_type=_QUANTITY,
        ),
    }
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
_PARALLEL_GATE_COUPLERS = _PARALLEL_GATES.entities("coupler")
_BUILD_PARALLEL_GATE_SET_PROGRAM = sc.compute(
    "build-parallel-gate-set-program",
    fn=build_parallel_gate_set_program,
    output_type=sc.ScalarType(sc.PayloadType("gate_sequence")),
    inputs={
        "gates": _PARALLEL_GATES,
        "gate_duration": GATE_DURATION,
    },
)
_RENDER_PARALLEL_GATE_DRIVE_WAVEFORMS = sc.compute(
    "render-parallel-gate-drive-waveforms",
    fn=render_parallel_gate_drive_waveforms,
    output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
    inputs={
        "program": _BUILD_PARALLEL_GATE_SET_PROGRAM.output,
        "drive_route": sc.route("drive"),
    },
)
_RENDER_PARALLEL_GATE_COUPLER_WAVEFORMS = sc.compute(
    "render-parallel-gate-coupler-waveforms",
    fn=render_parallel_gate_coupler_waveforms,
    output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
    inputs={
        "program": _BUILD_PARALLEL_GATE_SET_PROGRAM.output,
        "coupler_route": sc.route("coupler"),
    },
)

PARALLEL_GATE_SET_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.two_qubit.parallel_gate_set",
        metadata={"template_id": PARALLEL_GATE_SET_TEMPLATE_ID},
    )
    .inputs(_PARALLEL_GATE_KEYS)
    .resource(
        "drive",
        requires=("play_gate_sequence", "play_pulse_program"),
        for_entities=(PARALLEL_GATE_QUBITS,),
    )
    .resource(
        "coupler",
        requires=("play_coupler_pulse",),
        for_entities=(_PARALLEL_GATE_COUPLERS,),
    )
    .computes(
        _BUILD_PARALLEL_GATE_SET_PROGRAM,
        _RENDER_PARALLEL_GATE_DRIVE_WAVEFORMS,
        _RENDER_PARALLEL_GATE_COUPLER_WAVEFORMS,
    )
    .bind(
        "drive.play_gate_sequence.sequence",
        _BUILD_PARALLEL_GATE_SET_PROGRAM.output,
    )
    .bind(
        "drive.play_pulse_program.program",
        _RENDER_PARALLEL_GATE_DRIVE_WAVEFORMS.output,
    )
    .bind(
        "coupler.play_coupler_pulse.program",
        _RENDER_PARALLEL_GATE_COUPLER_WAVEFORMS.output,
    )
    .build()
)

__all__ = [
    "CZ_CHEVRON_MODULE",
    "PARALLEL_GATE_QUBITS",
    "PARALLEL_GATE_SET_MODULE",
    "PARALLEL_GATE_TABLE_TYPE",
]

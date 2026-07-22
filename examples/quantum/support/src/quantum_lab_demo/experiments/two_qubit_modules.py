"""Structural two-qubit fixtures for compute and resource-selection tests.

Executable two-qubit calibration examples belong in ``reference_experiments``
and use the unified ``scopecat_quantum.authoring`` gate/pulse DSL. In
particular, CZ conditional-phase calibration must not use the payload-shaped
``CZ_CHEVRON_MODULE`` below as its authoring surface.

``PARALLEL_GATE_SET_MODULE`` is the escape hatch for a lab without a domain
compiler. It enriches a table collection, passes the whole collection through
``sc.compute``, and binds the resulting opaque payloads to instrument fields.
"""

from __future__ import annotations

from typing import Annotated, cast

import scopecat as sc

from quantum_lab_demo.experiments.compute import (
    build_cz_chevron_program,
    build_parallel_gate_set_program,
    render_cz_coupler_waveforms,
    render_cz_drive_waveforms,
    render_parallel_gate_coupler_waveforms,
    render_parallel_gate_drive_waveforms,
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
from quantum_lab_demo.virtual_lab.parameters import (
    QUBIT_PARAMETER_TABLE,
    TWO_QUBIT_GATE_PARAMETER_TABLE,
)

_QUBIT = sc.ScalarType(sc.EntityType(entity_kind="logical_qubit"))
_COUPLER = sc.ScalarType(sc.EntityType(entity_kind="logical_coupler"))
_FLOAT = sc.ScalarType(sc.FloatType())
_QUANTITY = sc.ScalarType(sc.QuantityType())


def _cz_gate_param(
    column: str,
    *,
    control_qubit: sc.ValueRef,
    partner_qubit: sc.ValueRef,
) -> sc.ValueRef:
    return two_qubit_gate_param(
        column,
        control_qubit=control_qubit,
        partner_qubit=partner_qubit,
        value_type=_FLOAT if column == "sample_rate_hz" else _QUANTITY,
    )


@sc.module(id="quantum_lab_demo.experiments.two_qubit.cz_chevron")
def CZ_CHEVRON_MODULE(
    control_qubit: Annotated[sc.Input[str], _QUBIT],
    partner_qubit: Annotated[sc.Input[str], _QUBIT],
    coupler: Annotated[sc.Input[str], _COUPLER],
):
    control_qubit_ref = cast("sc.ValueRef", control_qubit)
    partner_qubit_ref = cast("sc.ValueRef", partner_qubit)
    coupler_ref = cast("sc.ValueRef", coupler)
    build_program = sc.compute(
        "build-cz-chevron-program",
        fn=build_cz_chevron_program,
        output_type=sc.ScalarType(sc.PayloadType("gate_sequence")),
        inputs={
            "control_qubit": control_qubit_ref,
            "partner_qubit": partner_qubit_ref,
            "coupler": coupler_ref,
            "duration": COUPLER_DURATION,
            "amplitude": COUPLER_AMPLITUDE,
            "control_echo_amplitude": _cz_gate_param(
                "control_echo_amplitude",
                control_qubit=control_qubit_ref,
                partner_qubit=partner_qubit_ref,
            ),
            "partner_echo_amplitude": _cz_gate_param(
                "partner_echo_amplitude",
                control_qubit=control_qubit_ref,
                partner_qubit=partner_qubit_ref,
            ),
            "coupler_parking_flux": _cz_gate_param(
                "coupler_parking_flux",
                control_qubit=control_qubit_ref,
                partner_qubit=partner_qubit_ref,
            ),
            "sample_rate_hz": _cz_gate_param(
                "sample_rate_hz",
                control_qubit=control_qubit_ref,
                partner_qubit=partner_qubit_ref,
            ),
            "control_drive_frequency": qubit_param(
                "drive_frequency",
                control_qubit_ref,
            ),
            "partner_drive_frequency": qubit_param(
                "drive_frequency",
                partner_qubit_ref,
            ),
        },
    )
    render_drive_waveforms = sc.compute(
        "render-cz-chevron-drive-waveforms",
        fn=render_cz_drive_waveforms,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={"program": build_program.output},
    )
    render_coupler_waveforms = sc.compute(
        "render-cz-chevron-coupler-waveforms",
        fn=render_cz_coupler_waveforms,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={"program": build_program.output},
    )
    return (
        sc.module_body()
        .resource(
            "drive",
            requires=("play_gate_sequence", "play_pulse_program"),
            for_entities=(control_qubit_ref, partner_qubit_ref),
        )
        .resource(
            "coupler",
            requires=("play_coupler_pulse",),
            for_entities=(coupler_ref,),
        )
        .computes(
            build_program,
            render_drive_waveforms,
            render_coupler_waveforms,
        )
        .bind_field(
            "drive",
            capability="play_gate_sequence",
            field="sequence",
            value=build_program.output,
        )
        .bind_field(
            "drive",
            capability="play_pulse_program",
            field="program",
            value=render_drive_waveforms.output,
        )
        .bind_field(
            "drive",
            capability="play_pulse_program",
            field="length",
            value=COUPLER_DURATION,
        )
        .bind_field(
            "drive",
            capability="play_pulse_program",
            field="amplitude",
            value=_cz_gate_param(
                "control_echo_amplitude",
                control_qubit=control_qubit_ref,
                partner_qubit=partner_qubit_ref,
            ),
        )
        .bind_field(
            "drive",
            capability="play_pulse_program",
            field="frequency",
            value=qubit_param("drive_frequency", control_qubit_ref),
        )
        .bind_field(
            "coupler",
            capability="play_coupler_pulse",
            field="program",
            value=render_coupler_waveforms.output,
        )
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

PARALLEL_GATE_QUBITS = sc.input("gates", PARALLEL_GATE_TABLE_TYPE).entities(
    "control_qubit",
    "partner_qubit",
)


@sc.module(id="quantum_lab_demo.experiments.two_qubit.parallel_gate_set")
def PARALLEL_GATE_SET_MODULE(
    gates: Annotated[
        sc.Input[tuple[dict[str, str], ...]],
        PARALLEL_GATE_TABLE_TYPE,
    ],
):
    gates_ref = cast("sc.ValueRef", gates)
    resolved_gates = gates_ref.with_columns(
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
    qubits = gates_ref.entities("control_qubit", "partner_qubit")
    couplers = resolved_gates.entities("coupler")
    build_program = sc.compute(
        "build-parallel-gate-set-program",
        fn=build_parallel_gate_set_program,
        output_type=sc.ScalarType(sc.PayloadType("gate_sequence")),
        inputs={
            "gates": resolved_gates,
            "gate_duration": GATE_DURATION,
        },
    )
    render_drive_waveforms = sc.compute(
        "render-parallel-gate-drive-waveforms",
        fn=render_parallel_gate_drive_waveforms,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={"program": build_program.output},
    )
    render_coupler_waveforms = sc.compute(
        "render-parallel-gate-coupler-waveforms",
        fn=render_parallel_gate_coupler_waveforms,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={"program": build_program.output},
    )
    return (
        sc.module_body()
        .resource(
            "drive",
            requires=("play_gate_sequence", "play_pulse_program"),
            for_entities=(qubits,),
        )
        .resource(
            "coupler",
            requires=("play_coupler_pulse",),
            for_entities=(couplers,),
        )
        .computes(
            build_program,
            render_drive_waveforms,
            render_coupler_waveforms,
        )
        .bind_field(
            "drive",
            capability="play_gate_sequence",
            field="sequence",
            value=build_program.output,
        )
        .bind_field(
            "drive",
            capability="play_pulse_program",
            field="program",
            value=render_drive_waveforms.output,
        )
        .bind_field(
            "coupler",
            capability="play_coupler_pulse",
            field="program",
            value=render_coupler_waveforms.output,
        )
    )


__all__ = [
    "CZ_CHEVRON_MODULE",
    "PARALLEL_GATE_QUBITS",
    "PARALLEL_GATE_SET_MODULE",
    "PARALLEL_GATE_TABLE_TYPE",
]

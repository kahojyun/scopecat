"""Static pulse recipes mapped over point-effective compiler parameters."""

from __future__ import annotations

import math

from scopecat import Quantity
from scopecat_quantum import (
    AcquisitionKind,
    PulseRecipeProfile,
    gate_pulse_recipe,
    map_qubit_pulse_recipes,
    measurement_pulse_recipe,
)
from scopecat_quantum import authoring as quantum
from scopecat_quantum.standard_gates import X90, XM90, Y90, YM90, X

from quantum_lab_demo.virtual_lab.compiler_parameters import (
    QuantumCompilerParameters,
    QubitPulseParameters,
)


def _constant_gate_fragment(
    row: QubitPulseParameters,
    target: quantum.Qubit,
) -> quantum.QuantumFragment:
    return quantum.play(
        quantum.drive(target),
        quantum.constant(
            duration=row.x_duration,
            amplitude=row.x_amplitude,
        ),
    )


def _drag_gate_fragment(
    row: QubitPulseParameters,
    target: quantum.Qubit,
    *,
    phase: Quantity,
) -> quantum.QuantumFragment:
    return quantum.play(
        quantum.drive(target),
        quantum.drag(
            duration=row.quarter_turn_duration,
            amplitude=row.quarter_turn_amplitude,
            sigma=row.quarter_turn_sigma,
            beta=row.drag_beta,
            phase=phase,
        ),
    )


@gate_pulse_recipe(of=X, id="x.constant")
def x_pulse_recipe(
    row: QubitPulseParameters,
    target: quantum.Qubit,
) -> quantum.QuantumFragment:
    return _constant_gate_fragment(row, target)


@gate_pulse_recipe(of=X90, id="x90.drag")
def x90_pulse_recipe(
    row: QubitPulseParameters,
    target: quantum.Qubit,
) -> quantum.QuantumFragment:
    return _drag_gate_fragment(row, target, phase=Quantity(0, "rad"))


@gate_pulse_recipe(of=XM90, id="xm90.drag")
def xm90_pulse_recipe(
    row: QubitPulseParameters,
    target: quantum.Qubit,
) -> quantum.QuantumFragment:
    return _drag_gate_fragment(row, target, phase=Quantity(math.pi, "rad"))


@gate_pulse_recipe(of=Y90, id="y90.drag")
def y90_pulse_recipe(
    row: QubitPulseParameters,
    target: quantum.Qubit,
) -> quantum.QuantumFragment:
    return _drag_gate_fragment(row, target, phase=Quantity(math.pi / 2, "rad"))


@gate_pulse_recipe(of=YM90, id="ym90.drag")
def ym90_pulse_recipe(
    row: QubitPulseParameters,
    target: quantum.Qubit,
) -> quantum.QuantumFragment:
    return _drag_gate_fragment(row, target, phase=Quantity(-math.pi / 2, "rad"))


@measurement_pulse_recipe(
    kind=AcquisitionKind.INTEGRATED_IQ,
    id="readout.integrated-iq",
)
def integrated_iq_pulse_recipe(
    row: QubitPulseParameters,
    target: quantum.Qubit,
) -> quantum.QuantumFragment:
    return quantum.parallel(
        quantum.play(
            quantum.readout(target),
            quantum.constant(
                duration=row.readout_duration,
                amplitude=row.readout_amplitude,
            ),
        ),
        quantum.acquire(
            target,
            duration=row.readout_duration,
            result="template-iq-result",
        ),
    )


QUANTUM_PULSE_PROFILE = PulseRecipeProfile[QuantumCompilerParameters](
    map_qubit_pulse_recipes(
        rows=lambda parameters: parameters.qubits,
        qubit=lambda row: row.qubit,
        gates=(
            x_pulse_recipe,
            x90_pulse_recipe,
            xm90_pulse_recipe,
            y90_pulse_recipe,
            ym90_pulse_recipe,
        ),
        measurements=(integrated_iq_pulse_recipe,),
    )
)


__all__ = [
    "QUANTUM_PULSE_PROFILE",
    "integrated_iq_pulse_recipe",
    "x90_pulse_recipe",
    "x_pulse_recipe",
    "xm90_pulse_recipe",
    "y90_pulse_recipe",
    "ym90_pulse_recipe",
]

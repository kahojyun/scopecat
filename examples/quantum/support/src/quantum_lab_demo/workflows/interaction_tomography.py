"""Gate-assisted tomography around a directly authored interaction layout."""

from __future__ import annotations

import math
from typing import Annotated

import scopecat as sc
from scopecat_quantum import authoring as q
from scopecat_quantum.standard_gates import X90, XM90, Y90, YM90, X

from quantum_lab_demo.virtual_lab.parameters import qubit_parameters

INTERACTION_TOMOGRAPHY_TEMPLATE_ID = "quantum_lab_demo.workflows.interaction_tomography"
INTERACTION_TOMOGRAPHY_EXPERIMENT_ID = "interaction-tomography"
INTERACTION_TOMOGRAPHY_SHOTS = 8

DEFAULT_PREPARATIONS = ("00", "10", "0+", "0+i")
DEFAULT_ANALYSIS_BASES = ("x", "y", "z")
DEFAULT_INTERACTION_AMPLITUDES = (
    sc.Quantity(0.02, "arb"),
    sc.Quantity(0.04, "arb"),
)

_PREPARATION_TYPE = sc.ScalarType(sc.StringType(choices=DEFAULT_PREPARATIONS))
_ANALYSIS_BASIS_TYPE = sc.ScalarType(sc.StringType(choices=DEFAULT_ANALYSIS_BASES))
_AMPLITUDE_TYPE = sc.ScalarType(sc.QuantityType(unit="arb"))

PREPARATION = sc.coordinate("preparation", _PREPARATION_TYPE)
ANALYSIS_BASIS = sc.coordinate("analysis_basis", _ANALYSIS_BASIS_TYPE)
INTERACTION_AMPLITUDE = sc.coordinate("interaction_amplitude", _AMPLITUDE_TYPE)

_INTERACTION_DURATION = sc.Quantity(48, "ns")
_CONTROL_DELAY = sc.Quantity(8, "ns")
_CONTROL_DRIVE_DURATION = sc.Quantity(32, "ns")
_CONTROL_DRIVE_AMPLITUDE = sc.Quantity(0.05, "arb")
_TARGET_DELAY = sc.Quantity(12, "ns")
_TARGET_DRIVE_DURATION = sc.Quantity(24, "ns")
_TARGET_DRIVE_AMPLITUDE = sc.Quantity(0.04, "arb")


@q.fragment(id="interaction-tomography.prepare")
def prepare_state(
    control: q.Qubit,
    target: q.Qubit,
    preparation: Annotated[str, _PREPARATION_TYPE],
) -> q.QuantumFragment:
    """Expand one declarative preparation label after its scan point binds."""

    return {
        "00": q.repeat(X(control), 0),
        "10": X(control),
        "0+": Y90(target),
        "0+i": XM90(target),
    }[preparation]


@q.fragment(id="interaction-tomography.analyze")
def analyze_target(
    target: q.Qubit,
    basis: Annotated[str, _ANALYSIS_BASIS_TYPE],
) -> q.QuantumFragment:
    """Map an analysis basis to the standard gate preceding Z readout."""

    return {
        "x": YM90(target),
        "y": X90(target),
        "z": q.repeat(X(target), 0),
    }[basis]


@q.pulse_template(id="interaction-tomography.direct-layout")
def interaction_pulse_layout(
    control: q.Qubit,
    target: q.Qubit,
    coupler: q.Coupler,
    amplitude: Annotated[sc.Quantity, _AMPLITUDE_TYPE],
) -> q.QuantumFragment:
    """Lay out synchronized controls that intentionally have no gate semantics."""

    control_drive = q.drive(control)
    target_drive = q.drive(target)
    coupler_flux = q.flux(coupler)
    return q.parallel(
        q.sequence(
            q.delay(control_drive, _CONTROL_DELAY),
            q.play(
                control_drive,
                q.constant(
                    duration=_CONTROL_DRIVE_DURATION,
                    amplitude=_CONTROL_DRIVE_AMPLITUDE,
                ),
            ),
            q.delay(control_drive, _CONTROL_DELAY),
        ),
        q.sequence(
            q.delay(target_drive, _TARGET_DELAY),
            q.play(
                target_drive,
                q.drag(
                    duration=_TARGET_DRIVE_DURATION,
                    amplitude=_TARGET_DRIVE_AMPLITUDE,
                    sigma=sc.Quantity(6, "ns"),
                    beta=sc.Quantity(1, "ns"),
                    phase=sc.Quantity(math.pi / 2, "rad"),
                ),
            ),
            q.delay(target_drive, _TARGET_DELAY),
        ),
        q.play(
            coupler_flux,
            q.constant(
                duration=_INTERACTION_DURATION,
                amplitude=amplitude,
            ),
        ),
    )


@q.program(id=INTERACTION_TOMOGRAPHY_EXPERIMENT_ID)
def interaction_tomography_program(
    control: q.Qubit,
    target: q.Qubit,
    coupler: q.Coupler,
    preparation: Annotated[str, _PREPARATION_TYPE],
    analysis_basis: Annotated[str, _ANALYSIS_BASIS_TYPE],
    interaction_amplitude: Annotated[sc.Quantity, _AMPLITUDE_TYPE],
) -> q.QuantumFragment:
    """Prepare, apply one raw interaction layout, rotate, and capture both qubits."""

    return q.sequence(
        prepare_state(control, target, preparation),
        interaction_pulse_layout(
            control,
            target,
            coupler,
            amplitude=interaction_amplitude,
        ),
        analyze_target(target, analysis_basis),
        q.parallel(
            q.measure(control, result="control_iq_shots"),
            q.measure(target, result="target_iq_shots"),
        ),
    )


@sc.template(
    id=INTERACTION_TOMOGRAPHY_TEMPLATE_ID,
    kind=INTERACTION_TOMOGRAPHY_EXPERIMENT_ID,
)
def interaction_tomography_template(
    control: q.QubitInput = "q0",
    target: q.QubitInput = "q1",
    coupler: q.CouplerInput = "coupler-q0-q1",
    shots: Annotated[sc.Input[int], sc.IntType(minimum=1)] = (
        INTERACTION_TOMOGRAPHY_SHOTS
    ),
) -> sc.ExperimentBody:
    """Acquire the compact preparation-by-basis interaction matrix."""

    call = (
        interaction_tomography_program(
            control=control,
            target=target,
            coupler=coupler,
            preparation=PREPARATION,
            analysis_basis=ANALYSIS_BASIS,
            interaction_amplitude=INTERACTION_AMPLITUDE,
        )
        .with_compiler_inputs(qubits=qubit_parameters())
        .with_shots(shots)
    )
    return (
        sc.experiment(call)
        .scan(
            sc.cartesian(
                sc.axis(PREPARATION, DEFAULT_PREPARATIONS),
                sc.axis(ANALYSIS_BASIS, DEFAULT_ANALYSIS_BASES),
                sc.axis(
                    INTERACTION_AMPLITUDE,
                    DEFAULT_INTERACTION_AMPLITUDES,
                ),
            )
        )
        .record_product(
            call.results.control_iq_shots,
            call.results.target_iq_shots,
        )
    )


__all__ = [
    "ANALYSIS_BASIS",
    "DEFAULT_ANALYSIS_BASES",
    "DEFAULT_INTERACTION_AMPLITUDES",
    "DEFAULT_PREPARATIONS",
    "INTERACTION_AMPLITUDE",
    "INTERACTION_TOMOGRAPHY_EXPERIMENT_ID",
    "INTERACTION_TOMOGRAPHY_SHOTS",
    "INTERACTION_TOMOGRAPHY_TEMPLATE_ID",
    "PREPARATION",
    "analyze_target",
    "interaction_pulse_layout",
    "interaction_tomography_program",
    "interaction_tomography_template",
    "prepare_state",
]

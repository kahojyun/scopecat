"""Conditional-phase Ramsey experiment for CZ calibration."""

from __future__ import annotations

import math

import scopecat as sc
from scopecat import Quantity
from scopecat_quantum.measurement_postprocessors import (
    BinaryIqDiscriminator,
    IqCentroid,
    binary_iq_probability_postprocessor,
)

from quantum_lab_demo.virtual_lab.parameters import (
    q0_q1_cz_amplitude_lookup,
    qubit_parameters,
)
from quantum_lab_demo.workflows.cz_phase_calibration import (
    cz_conditional_phase,
)

CZ_PHASE_TEMPLATE_ID = "quantum_lab_demo.workflows.cz_conditional_phase"
CZ_PHASE_EXPERIMENT_ID = "cz-conditional-phase"
CZ_PHASE_SHOTS = 128
CZ_AMPLITUDE_SPAN = Quantity(0.08, "arb")
CZ_AMPLITUDE_POINTS = 3
DEFAULT_CONTROL_STATES = (0, 1)
DEFAULT_ANALYZER_PHASES = tuple(
    Quantity(value, "rad")
    for value in (0.0, math.pi / 2.0, math.pi, 3.0 * math.pi / 2.0)
)

_AMPLITUDE_TYPE = sc.ScalarType(sc.QuantityType(unit="arb"))
_PHASE_TYPE = sc.ScalarType(sc.QuantityType(unit="rad"))
CZ_AMPLITUDE = sc.coordinate("coupler_amplitude", _AMPLITUDE_TYPE)
CONTROL_STATE = sc.coordinate(
    "control_state",
    sc.ScalarType(sc.IntType(minimum=0, maximum=1)),
)
ANALYZER_PHASE = sc.coordinate("analyzer_phase", _PHASE_TYPE)

_DISCRIMINATOR = BinaryIqDiscriminator(
    state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
    state_1_centroid=IqCentroid(real=1.0, imag=0.0),
    tie_policy="state_0",
)


@sc.module(id="quantum_lab_demo.workflows.cz_phase.capture")
def cz_phase_capture():
    call = (
        cz_conditional_phase(
            control="q0",
            target="q1",
            coupler="coupler-q0-q1",
            control_state=CONTROL_STATE,
            coupler_amplitude=q0_q1_cz_amplitude_lookup(),
            analyzer_phase=ANALYZER_PHASE,
        )
        .with_compiler_inputs(qubits=qubit_parameters())
        .with_shots(CZ_PHASE_SHOTS)
    )
    body = (
        sc.module_body()
        .use(call)
        .product(
            "control_probability_0",
            "control_probability_1",
            "target_probability_0",
            "target_probability_1",
            unit="ratio",
        )
    )
    control_postprocessor = binary_iq_probability_postprocessor(
        "control-binary-iq-probability",
        iq_shots=call.results.control_iq_shots,
        probability_0=body.products.control_probability_0,
        probability_1=body.products.control_probability_1,
        discriminator=_DISCRIMINATOR,
    )
    target_postprocessor = binary_iq_probability_postprocessor(
        "target-binary-iq-probability",
        iq_shots=call.results.target_iq_shots,
        probability_0=body.products.target_probability_0,
        probability_1=body.products.target_probability_1,
        discriminator=_DISCRIMINATOR,
    )
    return body.measurement_postprocessors(control_postprocessor, target_postprocessor)


@sc.template(
    id=CZ_PHASE_TEMPLATE_ID,
    kind=CZ_PHASE_EXPERIMENT_ID,
)
def cz_phase_template() -> sc.ExperimentBody:
    capture = cz_phase_capture()
    return (
        sc.experiment(capture)
        .scan(
            sc.cartesian(
                sc.param_axis(
                    CZ_AMPLITUDE,
                    q0_q1_cz_amplitude_lookup(),
                    span=CZ_AMPLITUDE_SPAN,
                    points=CZ_AMPLITUDE_POINTS,
                ),
                sc.axis(CONTROL_STATE, DEFAULT_CONTROL_STATES),
                sc.axis(ANALYZER_PHASE, DEFAULT_ANALYZER_PHASES),
            )
        )
        .record_product(
            capture.products.control_probability_1,
            capture.products.target_probability_1,
        )
    )


__all__ = [
    "ANALYZER_PHASE",
    "CONTROL_STATE",
    "CZ_AMPLITUDE",
    "CZ_AMPLITUDE_POINTS",
    "CZ_AMPLITUDE_SPAN",
    "CZ_PHASE_EXPERIMENT_ID",
    "CZ_PHASE_SHOTS",
    "CZ_PHASE_TEMPLATE_ID",
    "DEFAULT_ANALYZER_PHASES",
    "DEFAULT_CONTROL_STATES",
    "cz_phase_capture",
    "cz_phase_template",
]

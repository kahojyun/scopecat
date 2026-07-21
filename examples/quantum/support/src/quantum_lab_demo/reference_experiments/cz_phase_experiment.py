"""Workspace execution for conditional-phase Ramsey CZ calibration."""

from __future__ import annotations

import math

import scopecat as sc
from scopecat import Quantity
from scopecat_quantum import (
    BinaryIqDiscriminator,
    IqCentroid,
    binary_iq_probability_transform,
)
from scopecat_quantum import authoring as quantum

from quantum_lab_demo.reference_experiments.cz_phase_calibration import (
    ANALYZER_PHASE_INPUT,
    CONTROL_STATE_INPUT,
    CZ_AMPLITUDE_INPUT,
    cz_conditional_phase_program,
)
from quantum_lab_demo.virtual_lab.parameters import (
    CZ_AMPLITUDE_PARAMETER_COLUMN,
    q0_q1_cz_amplitude_lookup,
    q0_q1_cz_row,
)

CZ_PHASE_TEMPLATE_ID = "quantum_lab_demo.reference.cz_conditional_phase"
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
CZ_AMPLITUDE = sc.point("coupler_amplitude", _AMPLITUDE_TYPE)
CONTROL_STATE = sc.point(
    "control_state",
    sc.ScalarType(sc.IntType(minimum=0, maximum=1)),
)
ANALYZER_PHASE = sc.point("analyzer_phase", _PHASE_TYPE)

CZ_PHASE_PROGRAM = cz_conditional_phase_program()
[_CONTROL_RESULT, _TARGET_RESULT] = CZ_PHASE_PROGRAM.results
_CZ_DOMAIN_PROGRAM = quantum.domain_program(CZ_PHASE_PROGRAM)
_DISCRIMINATOR = BinaryIqDiscriminator(
    state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
    state_1_centroid=IqCentroid(real=1.0, imag=0.0),
    tie_policy="state_0",
)
_CONTROL_TRANSFORM = binary_iq_probability_transform(
    "control-binary-iq-probability",
    iq_shots="control_iq_shots",
    probability_0="control_probability_0",
    probability_1="control_probability_1",
    discriminator=_DISCRIMINATOR,
)
_TARGET_TRANSFORM = binary_iq_probability_transform(
    "target-binary-iq-probability",
    iq_shots="target_iq_shots",
    probability_0="target_probability_0",
    probability_1="target_probability_1",
    discriminator=_DISCRIMINATOR,
)

CZ_PHASE_CAPTURE_MODULE = (
    sc.module("quantum_lab_demo.reference.cz_phase.capture")
    .product(
        "control_iq_shots",
        unit="ratio",
        dtype="complex128",
        axes=(sc.shot_axis(CZ_PHASE_SHOTS),),
    )
    .product(
        "target_iq_shots",
        unit="ratio",
        dtype="complex128",
        axes=(sc.shot_axis(CZ_PHASE_SHOTS),),
    )
    .product(
        "control_probability_0",
        "control_probability_1",
        "target_probability_0",
        "target_probability_1",
        unit="ratio",
    )
    .measurement_transforms(_CONTROL_TRANSFORM, _TARGET_TRANSFORM)
    .build()
)

_TEMPLATE_CAPTURE = CZ_PHASE_CAPTURE_MODULE.instantiate("capture")
_CZ_EXECUTION = quantum.domain_execution(
    _CZ_DOMAIN_PROGRAM,
    inputs={
        CZ_AMPLITUDE_INPUT: q0_q1_cz_amplitude_lookup(),
        CONTROL_STATE_INPUT: CONTROL_STATE,
        ANALYZER_PHASE_INPUT: ANALYZER_PHASE,
    },
    results={
        _CONTROL_RESULT: _TEMPLATE_CAPTURE.products.control_iq_shots,
        _TARGET_RESULT: _TEMPLATE_CAPTURE.products.target_iq_shots,
    },
)
CZ_PHASE_TEMPLATE = (
    sc.module("quantum_lab_demo.reference.cz_phase.root")
    .use(_TEMPLATE_CAPTURE)
    .domain(_CZ_EXECUTION)
    .template(
        CZ_PHASE_TEMPLATE_ID,
        kind=CZ_PHASE_EXPERIMENT_ID,
    )
    .experiment_id(CZ_PHASE_EXPERIMENT_ID)
    .scan(
        sc.cartesian(
            sc.param_axis(
                CZ_AMPLITUDE,
                q0_q1_cz_row(),
                CZ_AMPLITUDE_PARAMETER_COLUMN,
                span=CZ_AMPLITUDE_SPAN,
                points=CZ_AMPLITUDE_POINTS,
            ),
            sc.axis(CONTROL_STATE, DEFAULT_CONTROL_STATES),
            sc.axis(ANALYZER_PHASE, DEFAULT_ANALYZER_PHASES),
        )
    )
    .record_product(
        _TEMPLATE_CAPTURE.products.control_probability_1,
        record_id="control_probability_1",
    )
    .record_product(
        _TEMPLATE_CAPTURE.products.target_probability_1,
        record_id="target_probability_1",
    )
    .label("CZ conditional-phase Ramsey")
    .description(
        "Resolve accepted single-qubit gates and one explicit coupler-flux CZ "
        "candidate inside the same typed Program."
    )
)


__all__ = [
    "ANALYZER_PHASE",
    "CONTROL_STATE",
    "CZ_AMPLITUDE",
    "CZ_AMPLITUDE_POINTS",
    "CZ_AMPLITUDE_SPAN",
    "CZ_PHASE_CAPTURE_MODULE",
    "CZ_PHASE_EXPERIMENT_ID",
    "CZ_PHASE_PROGRAM",
    "CZ_PHASE_SHOTS",
    "CZ_PHASE_TEMPLATE",
    "CZ_PHASE_TEMPLATE_ID",
    "DEFAULT_ANALYZER_PHASES",
    "DEFAULT_CONTROL_STATES",
]

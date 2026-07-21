"""Production X90 execution with config-bound DRAG and a fixed Xm90 reference."""

from __future__ import annotations

import scopecat as sc
from scopecat import Quantity
from scopecat_quantum import (
    BinaryIqDiscriminator,
    CircuitPulseEventProvenance,
    GateId,
    ImplementedGatePulseEventProvenance,
    IqCentroid,
    PreparedQuantumTargetEntry,
    PulseEventId,
    binary_iq_probability_transform,
)
from scopecat_quantum import authoring as quantum

from quantum_lab_demo.reference_experiments.drag_beta_calibration import (
    DEFAULT_BASELINE_BETA,
    DRAG_GATE_PULSE_TEMPLATE,
    DRAG_READOUT_PULSE_TEMPLATE,
    XM90_CALIBRATION_ID,
)
from quantum_lab_demo.virtual_lab.parameters import q0_drag_beta_lookup

PRODUCTION_DRAG_GATE_TEMPLATE_ID = "quantum_lab_demo.production.drag_x90"
PRODUCTION_DRAG_GATE_EXPERIMENT_ID = "production-drag-x90"
PRODUCTION_DRAG_GATE_SHOTS = 32
TRUSTED_REFERENCE_BETA = DEFAULT_BASELINE_BETA

_BETA_VALUE_TYPE = sc.ScalarType(sc.QuantityType(unit="ns"))
PRODUCTION_DRAG_BETA_INPUT = quantum.input("drag_beta", _BETA_VALUE_TYPE)

_Q0 = quantum.qubit("q0")
_X90 = quantum.single_qubit_gate("x90")
_XM90 = quantum.single_qubit_gate("xm90")


def production_drag_gate_program() -> quantum.Program:
    """Declare a production X90 followed by one fixed trusted Xm90."""

    production_x90 = quantum.implements(
        _X90(_Q0),
        DRAG_GATE_PULSE_TEMPLATE(
            _Q0,
            template_beta=PRODUCTION_DRAG_BETA_INPUT,
            template_phase=Quantity(0, "rad"),
        ),
    )
    capture = quantum.acquire(
        _Q0,
        duration=Quantity(8, "ns"),
        result="iq_shots",
    )
    return quantum.program(
        "production-drag-x90",
        quantum.sequence(
            production_x90,
            _XM90(_Q0),
            quantum.parallel(DRAG_READOUT_PULSE_TEMPLATE(_Q0), capture),
        ),
    )


PRODUCTION_DRAG_PROGRAM = production_drag_gate_program()
[_IQ_SHOTS_RESULT] = PRODUCTION_DRAG_PROGRAM.results
_PRODUCTION_DRAG_DOMAIN_PROGRAM = quantum.domain_program(PRODUCTION_DRAG_PROGRAM)
_DISCRIMINATOR = BinaryIqDiscriminator(
    state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
    state_1_centroid=IqCentroid(real=1.0, imag=0.0),
    tie_policy="state_0",
)
_PROBABILITY_TRANSFORM = binary_iq_probability_transform(
    "binary-iq-probability",
    iq_shots="integrated_iq_shots",
    probability_0="probability_0",
    probability_1="probability_1",
    discriminator=_DISCRIMINATOR,
)

PRODUCTION_DRAG_GATE_CAPTURE_MODULE = (
    sc.module("quantum_lab_demo.production.drag_x90.capture")
    .product(
        "integrated_iq_shots",
        unit="ratio",
        dtype="complex128",
        axes=(sc.shot_axis(PRODUCTION_DRAG_GATE_SHOTS),),
    )
    .product("probability_0", "probability_1", unit="ratio")
    .measurement_transforms(_PROBABILITY_TRANSFORM)
    .build()
)

_TEMPLATE_CAPTURE = PRODUCTION_DRAG_GATE_CAPTURE_MODULE.instantiate("capture")
_PRODUCTION_DRAG_EXECUTION = quantum.domain_execution(
    _PRODUCTION_DRAG_DOMAIN_PROGRAM,
    inputs={PRODUCTION_DRAG_BETA_INPUT: q0_drag_beta_lookup()},
    results={
        _IQ_SHOTS_RESULT: _TEMPLATE_CAPTURE.products.integrated_iq_shots,
    },
)
PRODUCTION_DRAG_GATE_TEMPLATE = (
    sc.module("quantum_lab_demo.production.drag_x90.root")
    .use(_TEMPLATE_CAPTURE)
    .domain(_PRODUCTION_DRAG_EXECUTION)
    .template(
        PRODUCTION_DRAG_GATE_TEMPLATE_ID,
        kind=PRODUCTION_DRAG_GATE_EXPERIMENT_ID,
    )
    .experiment_id(PRODUCTION_DRAG_GATE_EXPERIMENT_ID)
    .record_product(_TEMPLATE_CAPTURE.products.probability_0, record_id="probability_0")
    .record_product(_TEMPLATE_CAPTURE.products.probability_1, record_id="probability_1")
    .label("Production DRAG X90")
    .description(
        "Compile the active q0 DRAG beta into a production X90 while keeping "
        "the trusted Xm90 reference calibration fixed."
    )
)


def production_x90_event_id(entry: PreparedQuantumTargetEntry) -> PulseEventId:
    """Locate the config-bound production pulse without conflating it with trust.

    Production and reference pulses intentionally use different provenance: a
    calibration candidate should be judged against an independently accepted
    reference so the same implementation error cannot silently affect both.
    """

    selected = tuple(
        origin.address.event_id
        for origin in entry.event_origins
        if isinstance(origin.provenance, ImplementedGatePulseEventProvenance)
        and origin.provenance.gate_id == GateId("x90")
        and origin.provenance.candidate_id is None
        and origin.provenance.template_program_id.value == DRAG_GATE_PULSE_TEMPLATE.id
    )
    if len(selected) != 1:
        msg = "production gate must lower one non-candidate X90 implementation"
        raise ValueError(msg)
    [event_id] = selected
    return event_id


def trusted_xm90_event_id(entry: PreparedQuantumTargetEntry) -> PulseEventId:
    """Locate the accepted Xm90 pulse used as independent reference evidence."""

    selected = tuple(
        origin.address.event_id
        for origin in entry.event_origins
        if isinstance(origin.provenance, CircuitPulseEventProvenance)
        and origin.provenance.calibration_id == XM90_CALIBRATION_ID
    )
    if len(selected) != 1:
        msg = "production gate must lower one trusted Xm90 calibration"
        raise ValueError(msg)
    [event_id] = selected
    return event_id


__all__ = [
    "PRODUCTION_DRAG_BETA_INPUT",
    "PRODUCTION_DRAG_GATE_CAPTURE_MODULE",
    "PRODUCTION_DRAG_GATE_EXPERIMENT_ID",
    "PRODUCTION_DRAG_GATE_SHOTS",
    "PRODUCTION_DRAG_GATE_TEMPLATE",
    "PRODUCTION_DRAG_GATE_TEMPLATE_ID",
    "PRODUCTION_DRAG_PROGRAM",
    "TRUSTED_REFERENCE_BETA",
    "production_drag_gate_program",
    "production_x90_event_id",
    "trusted_xm90_event_id",
]

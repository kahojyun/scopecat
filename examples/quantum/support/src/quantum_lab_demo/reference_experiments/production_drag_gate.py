"""Production X90 execution with config-bound DRAG and a fixed Xm90 reference."""

from __future__ import annotations

from typing import Annotated

import scopecat as sc
from scopecat import Quantity, QuantityType
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

_X90 = quantum.single_qubit_gate("x90")
_XM90 = quantum.single_qubit_gate("xm90")


@quantum.program(id="production-drag-x90")
def production_drag_program(
    qubit: quantum.Qubit,
    drag_beta: Annotated[Quantity, QuantityType(unit="ns")],
) -> quantum.QuantumFragment:
    """Declare a production X90 followed by one fixed trusted Xm90."""

    production_x90 = quantum.implements(
        _X90(qubit),
        DRAG_GATE_PULSE_TEMPLATE(
            qubit,
            template_beta=drag_beta,
            template_phase=Quantity(0, "rad"),
        ),
    )
    capture = quantum.acquire(
        qubit,
        duration=Quantity(8, "ns"),
        result="iq_shots",
    )
    return quantum.sequence(
        production_x90,
        _XM90(qubit),
        quantum.parallel(DRAG_READOUT_PULSE_TEMPLATE(qubit), capture),
    )


_DISCRIMINATOR = BinaryIqDiscriminator(
    state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
    state_1_centroid=IqCentroid(real=1.0, imag=0.0),
    tie_policy="state_0",
)


@sc.module(id="quantum_lab_demo.production.drag_x90.capture")
def production_drag_capture():
    call = production_drag_program(
        qubit="q0",
        drag_beta=q0_drag_beta_lookup(),
        shots=PRODUCTION_DRAG_GATE_SHOTS,
    )
    body = (
        sc.module_body()
        .use(call)
        .product("probability_0", "probability_1", unit="ratio")
    )
    transform = binary_iq_probability_transform(
        "binary-iq-probability",
        iq_shots=call.results.iq_shots,
        probability_0=body.products.probability_0,
        probability_1=body.products.probability_1,
        discriminator=_DISCRIMINATOR,
    )
    return body.measurement_transforms(transform)


@sc.template(
    id=PRODUCTION_DRAG_GATE_TEMPLATE_ID,
    kind=PRODUCTION_DRAG_GATE_EXPERIMENT_ID,
    label="Production DRAG X90",
    description=(
        "Compile the active q0 DRAG beta into a production X90 while keeping "
        "the trusted Xm90 reference calibration fixed."
    ),
)
def production_drag_template() -> sc.ExperimentBody:
    capture = production_drag_capture()
    return (
        sc.experiment(capture)
        .record_product(capture.products.probability_0, record_id="probability_0")
        .record_product(capture.products.probability_1, record_id="probability_1")
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
    "PRODUCTION_DRAG_GATE_EXPERIMENT_ID",
    "PRODUCTION_DRAG_GATE_SHOTS",
    "PRODUCTION_DRAG_GATE_TEMPLATE_ID",
    "TRUSTED_REFERENCE_BETA",
    "production_drag_capture",
    "production_drag_program",
    "production_drag_template",
    "production_x90_event_id",
    "trusted_xm90_event_id",
]

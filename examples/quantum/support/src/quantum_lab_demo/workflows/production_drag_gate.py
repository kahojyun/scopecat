"""Production X90 execution with config-bound program and calibration inputs."""

from __future__ import annotations

from typing import Annotated

import scopecat as sc
from scopecat import Quantity, QuantityType
from scopecat_quantum import authoring as quantum
from scopecat_quantum._ids import GateId, PulseEventId, QubitId
from scopecat_quantum.measurement_postprocessors import (
    BinaryIqDiscriminator,
    IqCentroid,
    binary_iq_probability_postprocessor,
)
from scopecat_quantum.program_targets import PreparedQuantumTargetEntry
from scopecat_quantum.programs import (
    CircuitPulseEventProvenance,
    ImplementedGatePulseEventProvenance,
)
from scopecat_quantum.standard_gates import X90, XM90

from quantum_lab_demo.virtual_lab.parameters import (
    q0_drag_beta_lookup,
    qubit_parameters,
)
from quantum_lab_demo.virtual_lab.pulse_profile import xm90_pulse_recipe
from quantum_lab_demo.workflows.drag_beta_calibration import (
    drag_gate_pulse,
    drag_readout_pulse,
)

PRODUCTION_DRAG_GATE_TEMPLATE_ID = "quantum_lab_demo.production.drag_x90"
PRODUCTION_DRAG_GATE_EXPERIMENT_ID = "production-drag-x90"
PRODUCTION_DRAG_GATE_SHOTS = 32


@quantum.implementation(of=X90, id="production-drag-x90.implementation")
def production_x90(
    qubit: quantum.Qubit,
    drag_beta: Annotated[Quantity, QuantityType(unit="ns")],
) -> quantum.QuantumFragment:
    return drag_gate_pulse(
        qubit,
        beta=drag_beta,
        phase=Quantity(0, "rad"),
    )


@quantum.program(id="production-drag-x90")
def production_drag_program(
    qubit: quantum.Qubit,
    drag_beta: Annotated[Quantity, QuantityType(unit="ns")],
) -> quantum.QuantumFragment:
    """Declare a production X90 followed by one accepted Xm90 calibration."""

    capture = quantum.acquire(
        qubit,
        duration=Quantity(8, "ns"),
        result="iq_shots",
    )
    return quantum.sequence(
        production_x90(qubit, drag_beta=drag_beta),
        XM90(qubit),
        quantum.parallel(drag_readout_pulse(qubit), capture),
    )


_DISCRIMINATOR = BinaryIqDiscriminator(
    state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
    state_1_centroid=IqCentroid(real=1.0, imag=0.0),
    tie_policy="state_0",
)


@sc.module(id="quantum_lab_demo.production.drag_x90.capture")
def production_drag_capture():
    call = (
        production_drag_program(
            qubit="q0",
            drag_beta=q0_drag_beta_lookup(),
        )
        .with_compiler_inputs(qubits=qubit_parameters())
        .with_shots(PRODUCTION_DRAG_GATE_SHOTS)
    )
    body = (
        sc.module_body()
        .use(call)
        .product("probability_0", "probability_1", unit="ratio")
    )
    postprocessor = binary_iq_probability_postprocessor(
        "binary-iq-probability",
        iq_shots=call.results.iq_shots,
        probability_0=body.products.probability_0,
        probability_1=body.products.probability_1,
        discriminator=_DISCRIMINATOR,
    )
    return body.measurement_postprocessors(postprocessor)


@sc.template(
    id=PRODUCTION_DRAG_GATE_TEMPLATE_ID,
    kind=PRODUCTION_DRAG_GATE_EXPERIMENT_ID,
)
def production_drag_template() -> sc.ExperimentBody:
    capture = production_drag_capture()
    return sc.experiment(capture).record_product(
        capture.products.probability_0,
        capture.products.probability_1,
    )


def production_x90_event_id(entry: PreparedQuantumTargetEntry) -> PulseEventId:
    """Locate the config-bound production pulse by implementation provenance.

    Production and accepted calibration pulses retain different provenance even
    when both read the same point-effective parameter collection.
    """

    selected = tuple(
        origin.address.event_id
        for origin in entry.event_origins
        if isinstance(origin.provenance, ImplementedGatePulseEventProvenance)
        and origin.provenance.gate_id == GateId("x90")
        and origin.provenance.candidate_id is None
        and origin.provenance.template_program_id.value == production_x90.id
    )
    if len(selected) != 1:
        msg = "production gate must lower one non-candidate X90 implementation"
        raise ValueError(msg)
    [event_id] = selected
    return event_id


def accepted_xm90_event_id(entry: PreparedQuantumTargetEntry) -> PulseEventId:
    """Locate the accepted Xm90 pulse by calibration provenance."""

    selected = tuple(
        origin.address.event_id
        for origin in entry.event_origins
        if isinstance(origin.provenance, CircuitPulseEventProvenance)
        and origin.provenance.implementation_id
        == xm90_pulse_recipe.implementation_id((QubitId("q0"),))
    )
    if len(selected) != 1:
        msg = "production gate must lower one accepted Xm90 calibration"
        raise ValueError(msg)
    [event_id] = selected
    return event_id


__all__ = [
    "PRODUCTION_DRAG_GATE_EXPERIMENT_ID",
    "PRODUCTION_DRAG_GATE_SHOTS",
    "PRODUCTION_DRAG_GATE_TEMPLATE_ID",
    "accepted_xm90_event_id",
    "production_drag_capture",
    "production_drag_program",
    "production_drag_template",
    "production_x90",
    "production_x90_event_id",
]

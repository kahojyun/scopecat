"""Lab-owned experiment policy for directly runnable quantum programs."""

from __future__ import annotations

import scopecat as sc
from scopecat.kernel.entity import EntityRef
from scopecat_instruments import rf_output
from scopecat_quantum import authoring as quantum
from scopecat_quantum.measurement_postprocessors import (
    BinaryIqDiscriminator,
    BinaryIqProbabilityProducts,
    IqCentroid,
    binary_iq_probabilities,
)

from reference_lab.parameters import (
    DRIVE_LO_A,
    DRIVE_LO_B,
    DRIVE_Q0_IQ_CHAIN,
    DRIVE_Q1_IQ_CHAIN,
    DRIVE_Q2_IQ_CHAIN,
    DRIVE_Q3_IQ_CHAIN,
    LO_FREQUENCY,
    LO_POWER,
    QUBITS,
    READOUT_LO,
)
from reference_lab.physical_policies import ensure_grouped_iq_offsets

Q0 = EntityRef(id="q0", kind="logical_qubit")
Q1 = EntityRef(id="q1", kind="logical_qubit")
Q2 = EntityRef(id="q2", kind="logical_qubit")
Q3 = EntityRef(id="q3", kind="logical_qubit")
QUANTUM_QUBITS = sc.each(Q0, Q1, Q2, Q3)
DRIVE_IQ_CHAINS = (
    (Q0, DRIVE_Q0_IQ_CHAIN),
    (Q1, DRIVE_Q1_IQ_CHAIN),
    (Q2, DRIVE_Q2_IQ_CHAIN),
    (Q3, DRIVE_Q3_IQ_CHAIN),
)

BINARY_IQ_DISCRIMINATOR = BinaryIqDiscriminator(
    state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
    state_1_centroid=IqCentroid(real=1.0, imag=0.0),
    tie_policy="state_0",
)


@sc.module(id="quantum-lab.capture")
def quantum_capture(
    module: sc.ModuleContext,
    call: quantum.QuantumProgramCall,
    *,
    prepare_los: bool = True,
) -> BinaryIqProbabilityProducts:
    """Apply reviewed lab preparation and capture policy to a quantum call.

    Most experiments use the reviewed LO setpoints below. A host-side LO sweep
    opts out and authors its changing state explicitly around this module.
    """

    prepare_quantum_hardware(module, prepare_los=prepare_los)
    configured = call.with_compiler_inputs(qubits=QUBITS.ref)
    results = module.use(configured)
    return binary_iq_probabilities(
        module,
        results.iq_shots,
        discriminator=BINARY_IQ_DISCRIMINATOR,
    )


def prepare_quantum_hardware(
    context: sc.ExperimentContext | sc.ModuleContext,
    *,
    prepare_los: bool = True,
) -> None:
    """Apply lab-owned physical state required by a direct quantum call."""

    ensure_grouped_iq_offsets(
        context,
        qubits=QUANTUM_QUBITS,
        drive_iq_chains=DRIVE_IQ_CHAINS,
    )
    if prepare_los:
        _prepare_reviewed_los(context)


def _prepare_reviewed_los(
    context: sc.ExperimentContext | sc.ModuleContext,
) -> None:
    drive_los = rf_output(context, for_=QUANTUM_QUBITS, role="drive-lo")
    drive_los.ensure(
        frequency=sc.PerEntity(
            (
                (Q0, DRIVE_LO_A[LO_FREQUENCY].ref),
                (Q1, DRIVE_LO_A[LO_FREQUENCY].ref),
                (Q2, DRIVE_LO_B[LO_FREQUENCY].ref),
                (Q3, DRIVE_LO_B[LO_FREQUENCY].ref),
            )
        ),
        power=sc.PerEntity(
            (
                (Q0, DRIVE_LO_A[LO_POWER].ref),
                (Q1, DRIVE_LO_A[LO_POWER].ref),
                (Q2, DRIVE_LO_B[LO_POWER].ref),
                (Q3, DRIVE_LO_B[LO_POWER].ref),
            )
        ),
        output_enabled=True,
        reference_source="external",
    )
    readout_lo = rf_output(context, for_=QUANTUM_QUBITS, role="readout-lo")
    readout_lo.ensure(
        frequency=READOUT_LO[LO_FREQUENCY].ref,
        power=READOUT_LO[LO_POWER].ref,
        output_enabled=True,
        reference_source="external",
    )


@sc.experiment
def run_quantum(
    experiment: sc.ExperimentContext,
    call: quantum.QuantumProgramCall,
) -> BinaryIqProbabilityProducts:
    """Run an integrated-IQ program through the lab-owned experiment skeleton.

    Independent local-device work, including external LO preparation, belongs
    here. Only hardware that participates in the prepared real-time program is
    part of the quantum target/compiler contract.
    """

    return experiment.use(quantum_capture(call))


__all__ = [
    "BINARY_IQ_DISCRIMINATOR",
    "prepare_quantum_hardware",
    "quantum_capture",
    "run_quantum",
]

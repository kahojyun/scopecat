"""Lab-owned experiment policy for directly runnable quantum programs."""

from __future__ import annotations

import scopecat as sc
from scopecat_quantum import authoring as quantum
from scopecat_quantum.measurement_postprocessors import (
    BinaryIqDiscriminator,
    BinaryIqProbabilityProducts,
    IqCentroid,
    binary_iq_probabilities,
)

from reference_lab.parameters import QUBITS

_BINARY_IQ_DISCRIMINATOR = BinaryIqDiscriminator(
    state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
    state_1_centroid=IqCentroid(real=1.0, imag=0.0),
    tie_policy="state_0",
)


@sc.module(id="quantum-lab.capture")
def quantum_capture(
    module: sc.ModuleContext,
    call: quantum.QuantumProgramCall,
) -> BinaryIqProbabilityProducts:
    """Apply reusable lab capture policy to an integrated-IQ program call."""

    configured = call.with_compiler_inputs(qubits=QUBITS.ref)
    results = module.use(configured)
    return binary_iq_probabilities(
        module,
        results.iq_shots,
        discriminator=_BINARY_IQ_DISCRIMINATOR,
    )


@sc.experiment
def run_quantum(
    experiment: sc.ExperimentContext,
    call: quantum.QuantumProgramCall,
) -> None:
    """Run an integrated-IQ program through the lab-owned experiment skeleton.

    Independent local-device work and additional domain calls belong here when
    the lab needs them. Hardware that must vary synchronously for every quantum
    point remains part of the quantum target/compiler contract.
    """

    experiment.record(experiment.use(quantum_capture(call)))


__all__ = ["quantum_capture", "run_quantum"]

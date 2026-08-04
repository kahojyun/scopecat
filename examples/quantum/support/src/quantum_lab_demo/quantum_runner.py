"""Lab-owned experiment policy for directly runnable quantum programs."""

from __future__ import annotations

import scopecat as sc
from scopecat_quantum import authoring as quantum
from scopecat_quantum.measurement_postprocessors import (
    BinaryIqDiscriminator,
    IqCentroid,
    binary_iq_probabilities,
)

from quantum_lab_demo.virtual_lab.parameters import qubit_parameters

_BINARY_IQ_DISCRIMINATOR = BinaryIqDiscriminator(
    state_0_centroid=IqCentroid(real=-1.0, imag=0.0),
    state_1_centroid=IqCentroid(real=1.0, imag=0.0),
    tie_policy="state_0",
)


def author_quantum_experiment(
    experiment: sc.ExperimentContext,
    call: quantum.QuantumProgramCall,
) -> None:
    """Apply lab policy to an integrated-IQ call exposing ``iq_shots``."""

    configured = call.with_compiler_inputs(qubits=qubit_parameters())
    placed = experiment.use(configured)
    probabilities = binary_iq_probabilities(
        experiment,
        placed.results.iq_shots,
        discriminator=_BINARY_IQ_DISCRIMINATOR,
    )
    experiment.record(probabilities, namespace="capture")


@sc.experiment_factory(id="quantum_lab_demo.run_quantum", kind="quantum")
def run_quantum(
    experiment: sc.ExperimentContext,
    call: quantum.QuantumProgramCall,
) -> None:
    """Run an integrated-IQ program through the lab-owned experiment skeleton.

    Independent local-device work and additional domain calls belong here when
    the lab needs them. Hardware that must vary synchronously for every quantum
    point remains part of the quantum target/compiler contract.
    """

    author_quantum_experiment(experiment, call)


__all__ = ["author_quantum_experiment", "run_quantum"]

"""Progressive Ramsey experiments over the reference lab channel map."""

from __future__ import annotations

from dataclasses import dataclass

import scopecat as sc
from scopecat.kernel.entity import EntityRef
from scopecat_instruments import DCSourceTarget, dc_source
from scopecat_quantum.measurement_postprocessors import (
    BinaryIqProbabilityRecords,
    binary_iq_probabilities,
)

from reference_lab.parameters import QUBITS
from reference_lab.quantum_runner import (
    BINARY_IQ_DISCRIMINATOR,
    quantum_capture,
)
from reference_lab.workflows.flux_spectroscopy import FLUX_SOURCE_RESOURCE
from reference_lab.workflows.ramsey import (
    conflicting_drive_program,
    parallel_two_qubit_ramsey_program,
    ramsey_program,
)

Q0 = EntityRef(id="q0", kind="logical_qubit")
Q1 = EntityRef(id="q1", kind="logical_qubit")
RAMSEY_SHOTS = 64
RAMSEY_DELAYS = tuple(sc.Quantity(value, "ns") for value in (8, 48, 88, 128, 168))
FLUX_BIASES = tuple(sc.Quantity(value, "V") for value in (-0.10, 0.0, 0.10))


@dataclass(frozen=True, slots=True)
class RamseyDataset:
    delay: sc.CoordinateRef[sc.Quantity]
    probabilities: BinaryIqProbabilityRecords


@sc.experiment(id="reference_lab.conflicting_drive")
def conflicting_drive(experiment: sc.ExperimentContext) -> None:
    """Author a deliberately invalid same-channel parallel pulse plan."""

    experiment.use(
        conflicting_drive_program(qubit="q0").with_compiler_inputs(qubits=QUBITS.ref)
    )


@sc.experiment(id="reference_lab.q0_ramsey")
def q0_ramsey(experiment: sc.ExperimentContext) -> RamseyDataset:
    """Run a delay scan on q0 through its configured drive/readout channels."""

    delay = experiment.scan("delay", RAMSEY_DELAYS)
    probabilities = experiment.record(
        experiment.use(
            quantum_capture(
                ramsey_program(
                    qubit="q0",
                    delay=delay,
                    phase=sc.Quantity(0.0, "rad"),
                ).with_shots(RAMSEY_SHOTS)
            )
        )
    )
    return RamseyDataset(delay=delay, probabilities=probabilities)


@dataclass(frozen=True, slots=True)
class FluxRamseyDataset:
    dc_bias: sc.CoordinateRef[sc.Quantity]
    delay: sc.CoordinateRef[sc.Quantity]
    probabilities: BinaryIqProbabilityRecords


@sc.experiment(id="reference_lab.flux_ramsey")
def flux_ramsey(experiment: sc.ExperimentContext) -> FluxRamseyDataset:
    """Compose q0 flux bias with a two-dimensional Ramsey scan."""

    dc_bias = experiment.scan("dc_bias", FLUX_BIASES)
    delay = experiment.scan("delay", RAMSEY_DELAYS)
    source = dc_source(experiment, FLUX_SOURCE_RESOURCE, for_=sc.one(Q0))
    source.ensure(
        current_protection=sc.Quantity(100.0, "uA"),
        output_enabled=False,
    )
    source.source_voltage(range=sc.Quantity(1.0, "V"), level=dc_bias)
    source.ensure(output_enabled=True)
    probabilities = experiment.record(
        experiment.use(
            quantum_capture(
                ramsey_program(
                    qubit="q0",
                    delay=delay,
                    phase=sc.Quantity(0.0, "rad"),
                ).with_shots(RAMSEY_SHOTS)
            )
        )
    )
    experiment.on_success(source, DCSourceTarget(output_enabled=False))
    return FluxRamseyDataset(
        dc_bias=dc_bias,
        delay=delay,
        probabilities=probabilities,
    )


@dataclass(frozen=True, slots=True)
class EntityRamseyDataset:
    qubit: sc.CoordinateRef[EntityRef]
    delay: sc.CoordinateRef[sc.Quantity]
    probabilities: BinaryIqProbabilityRecords


@sc.experiment(id="reference_lab.entity_routed_ramsey")
def entity_routed_ramsey(experiment: sc.ExperimentContext) -> EntityRamseyDataset:
    """Reuse one Ramsey definition while point-locally selecting q0 and q1."""

    qubit = experiment.scan("qubit", (Q0, Q1))
    delay = experiment.scan("delay", RAMSEY_DELAYS[:3])
    probabilities = experiment.record(
        experiment.use(
            quantum_capture(
                ramsey_program(
                    qubit=qubit,
                    delay=delay,
                    phase=sc.Quantity(0.0, "rad"),
                ).with_shots(RAMSEY_SHOTS)
            )
        )
    )
    return EntityRamseyDataset(
        qubit=qubit,
        delay=delay,
        probabilities=probabilities,
    )


@dataclass(frozen=True, slots=True)
class ParallelRamseyDataset:
    delay: sc.CoordinateRef[sc.Quantity]
    q0: BinaryIqProbabilityRecords
    q1: BinaryIqProbabilityRecords


@dataclass(frozen=True, slots=True)
class ParallelRawRamseyDataset:
    delay: sc.CoordinateRef[sc.Quantity]
    q0_iq: sc.RecordRef
    q1_iq: sc.RecordRef


@sc.experiment(id="reference_lab.parallel_raw_ramsey")
def parallel_raw_ramsey(experiment: sc.ExperimentContext) -> ParallelRawRamseyDataset:
    """Retain raw per-channel IQ so one unavailable demodulator stays visible."""

    delay = experiment.scan(
        "delay",
        (sc.Quantity(88, "ns"), sc.Quantity(128, "ns")),
    )
    call = parallel_two_qubit_ramsey_program(
        q0="q0",
        q1="q1",
        delay=delay,
        q0_phase=sc.Quantity(0.0, "rad"),
        q1_phase=sc.Quantity(0.4, "rad"),
    ).with_shots(RAMSEY_SHOTS)
    results = experiment.use(call.with_compiler_inputs(qubits=QUBITS.ref))
    return ParallelRawRamseyDataset(
        delay=delay,
        q0_iq=experiment.record(results.q0_iq_shots),
        q1_iq=experiment.record(results.q1_iq_shots),
    )


@sc.experiment(id="reference_lab.parallel_two_qubit_ramsey")
def parallel_two_qubit_ramsey(
    experiment: sc.ExperimentContext,
) -> ParallelRamseyDataset:
    """Compile synchronized q0/q1 Ramsey branches onto independent channels."""

    delay = experiment.scan("delay", RAMSEY_DELAYS[:3])
    call = parallel_two_qubit_ramsey_program(
        q0="q0",
        q1="q1",
        delay=delay,
        q0_phase=sc.Quantity(0.0, "rad"),
        q1_phase=sc.Quantity(0.4, "rad"),
    ).with_shots(RAMSEY_SHOTS)
    results = experiment.use(call.with_compiler_inputs(qubits=QUBITS.ref))
    q0_products = binary_iq_probabilities(
        experiment,
        results.q0_iq_shots,
        discriminator=BINARY_IQ_DISCRIMINATOR,
        id="q0-discrimination",
        output_prefix="q0",
    )
    q1_products = binary_iq_probabilities(
        experiment,
        results.q1_iq_shots,
        discriminator=BINARY_IQ_DISCRIMINATOR,
        id="q1-discrimination",
        output_prefix="q1",
    )
    return ParallelRamseyDataset(
        delay=delay,
        q0=experiment.record(q0_products),
        q1=experiment.record(q1_products),
    )


__all__ = [
    "RAMSEY_DELAYS",
    "RAMSEY_SHOTS",
    "EntityRamseyDataset",
    "FluxRamseyDataset",
    "ParallelRamseyDataset",
    "ParallelRawRamseyDataset",
    "RamseyDataset",
    "conflicting_drive",
    "entity_routed_ramsey",
    "flux_ramsey",
    "parallel_raw_ramsey",
    "parallel_two_qubit_ramsey",
    "q0_ramsey",
]

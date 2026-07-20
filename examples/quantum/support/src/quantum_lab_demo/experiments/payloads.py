"""Pure in-memory program payloads."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import scopecat as sc
from numpy.typing import NDArray


@dataclass(frozen=True)
class RabiGate:
    name: str
    qubit: str
    length: sc.Quantity
    amplitude: sc.Quantity
    frequency: sc.Quantity


@dataclass(frozen=True)
class RabiGateSequence:
    gates: tuple[RabiGate, ...]
    compiler_id: str


@dataclass(frozen=True)
class ReadoutPulseProgram:
    qubits: tuple[str, ...]
    frequency: sc.Quantity
    power: sc.Quantity
    compiler_id: str


@dataclass(frozen=True)
class RandomizedBenchmarkingSequence:
    qubits: tuple[str, ...]
    coupler: str | None
    clifford_count: int
    seed: int
    interleaved_gate: str | None
    compiler_id: str


@dataclass(frozen=True)
class RandomizedBenchmarkingPulseBundle:
    source_program_id: str
    entity_ids: tuple[str, ...]
    samples: NDArray[np.complex128]


@dataclass(frozen=True)
class CzDrivePulse:
    qubit: str
    amplitude: sc.Quantity
    frequency: sc.Quantity


@dataclass(frozen=True)
class CzCouplerPulse:
    coupler: str
    duration: sc.Quantity
    amplitude: sc.Quantity
    parking_flux: sc.Quantity


@dataclass(frozen=True)
class CzChevronProgram:
    control_qubit: str
    partner_qubit: str
    coupler: str
    drive_pulses: tuple[CzDrivePulse, ...]
    coupler_pulse: CzCouplerPulse
    sample_rate_hz: float
    compiler_id: str
    parameters: tuple[str, ...]


@dataclass(frozen=True)
class RenderedWaveformBundle:
    source_program_id: str
    entity_ids: tuple[str, ...]
    sample_rate_hz: float
    samples: NDArray[np.complex128]


@dataclass(frozen=True)
class ParallelCzGate:
    control_qubit: str
    partner_qubit: str
    coupler: str
    duration: sc.Quantity
    amplitude: sc.Quantity
    control_frequency: sc.Quantity
    partner_frequency: sc.Quantity


@dataclass(frozen=True)
class ParallelGateSetProgram:
    gates: tuple[ParallelCzGate, ...]
    compiler_id: str
    parameters: tuple[str, ...]


@dataclass(frozen=True)
class SurfaceCodeRoundProgram:
    patch_qubits: tuple[str, ...]
    data_qubits: tuple[str, ...]
    ancilla_qubits: tuple[str, ...]
    couplers: tuple[str, ...]
    rounds: int
    cycle_time: sc.Quantity
    schedule: tuple[str, ...]
    compiler_id: str


@dataclass(frozen=True)
class RepeatedMeasurementProgram:
    qubit: str
    rounds: int
    shots: int
    readout_frequency: sc.Quantity
    compiler_id: str


@dataclass(frozen=True)
class BackendBatchJob:
    logical_points: int
    submitted_point_uids: tuple[str, ...]
    returned_order: tuple[int, ...]
    seed: int
    compiler_id: str


__all__ = [
    "BackendBatchJob",
    "CzChevronProgram",
    "CzCouplerPulse",
    "CzDrivePulse",
    "ParallelCzGate",
    "ParallelGateSetProgram",
    "RabiGate",
    "RabiGateSequence",
    "RandomizedBenchmarkingPulseBundle",
    "RandomizedBenchmarkingSequence",
    "ReadoutPulseProgram",
    "RenderedWaveformBundle",
    "RepeatedMeasurementProgram",
    "SurfaceCodeRoundProgram",
]

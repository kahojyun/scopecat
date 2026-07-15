"""compute functions used by experiment modules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import SupportsInt, cast

import numpy as np
import scopecat as sc
from numpy.typing import NDArray

from quantum_lab_demo.experiments.ids import (
    QUBIT_PARAMETER_TABLE,
    TWO_QUBIT_GATE_PARAMETER_TABLE,
)
from quantum_lab_demo.experiments.payloads import (
    BackendBatchJob,
    CzChevronProgram,
    CzCouplerPulse,
    CzDrivePulse,
    ParallelCzGate,
    ParallelGateSetProgram,
    RabiGate,
    RabiGateSequence,
    RandomizedBenchmarkingPulseBundle,
    RandomizedBenchmarkingSequence,
    ReadoutPulseProgram,
    RenderedWaveformBundle,
    RepeatedMeasurementProgram,
    SurfaceCodeRoundProgram,
)


def build_rabi_gate_sequence(
    *,
    qubit: str | sc.EntityRef,
    length: sc.Quantity,
    amplitude: sc.Quantity,
    frequency: sc.Quantity,
) -> RabiGateSequence:
    qubit_id = _required_str(qubit, "qubit")
    return RabiGateSequence(
        gates=(
            RabiGate(
                name="x90",
                qubit=qubit_id,
                length=length,
                amplitude=amplitude,
                frequency=frequency,
            ),
        ),
        compiler_id="quantum_lab_demo.experiments.rabi_sequence.v1",
    )


def build_readout_program(
    *,
    qubit: str | sc.EntityRef,
    frequency: sc.Quantity,
    power: sc.Quantity,
) -> ReadoutPulseProgram:
    qubit_id = _required_str(qubit, "qubit")
    return ReadoutPulseProgram(
        qubits=(qubit_id,),
        frequency=frequency,
        power=power,
        compiler_id="quantum_lab_demo.experiments.readout_program.v1",
    )


def build_multiplexed_readout_program(
    *,
    qubits: Sequence[str | sc.EntityRef],
    frequency: sc.Quantity,
    power: sc.Quantity,
) -> ReadoutPulseProgram:
    return ReadoutPulseProgram(
        qubits=_entity_ids(qubits),
        frequency=frequency,
        power=power,
        compiler_id="quantum_lab_demo.experiments.multiplexed_readout_program.v1",
    )


def build_sqg_rb_sequence(
    *,
    qubit: str | sc.EntityRef,
    clifford_count: int,
    seed: int,
) -> RandomizedBenchmarkingSequence:
    qubit_id = _required_str(qubit, "qubit")
    return RandomizedBenchmarkingSequence(
        qubits=(qubit_id,),
        coupler=None,
        clifford_count=_required_int(clifford_count, "clifford_count"),
        seed=seed,
        interleaved_gate=None,
        compiler_id="quantum_lab_demo.experiments.sqg_rb_sequence.v1",
    )


def render_sqg_rb_pulse_program(
    *,
    sequence: RandomizedBenchmarkingSequence,
    drive_route: sc.ResolvedRoute,
) -> RandomizedBenchmarkingPulseBundle:
    count = max(8, sequence.clifford_count * 4)
    rng = np.random.default_rng(sequence.seed)
    samples = rng.normal(size=count) + 1j * rng.normal(size=count)
    return RandomizedBenchmarkingPulseBundle(
        source_program_id=sequence.compiler_id,
        resource_id=drive_route.resource_id,
        entity_ids=tuple(drive_route.entity_ids),
        channel_order=tuple(drive_route.product_axis_order),
        samples=np.asarray(0.04 * samples, dtype=np.complex128),
    )


def build_cz_rb_sequence(
    *,
    control_qubit: str,
    partner_qubit: str,
    coupler: str,
    clifford_count: int,
    seed: int,
    interleaved_gate: str,
) -> RandomizedBenchmarkingSequence:
    return RandomizedBenchmarkingSequence(
        qubits=(control_qubit, partner_qubit),
        coupler=coupler,
        clifford_count=_required_int(clifford_count, "clifford_count"),
        seed=seed,
        interleaved_gate=interleaved_gate,
        compiler_id="quantum_lab_demo.experiments.cz_rb_sequence.v1",
    )


def render_cz_rb_coupler_pulse(
    *,
    sequence: RandomizedBenchmarkingSequence,
    coupler_route: sc.ResolvedRoute,
) -> RandomizedBenchmarkingPulseBundle:
    count = max(8, sequence.clifford_count * 6)
    phase = 0.0 if sequence.interleaved_gate == "CZ" else np.pi / 4.0
    t = np.linspace(0.0, 2.0 * np.pi, count, dtype=np.float64)
    samples = 0.08 * np.sin(t + phase)
    return RandomizedBenchmarkingPulseBundle(
        source_program_id=sequence.compiler_id,
        resource_id=coupler_route.resource_id,
        entity_ids=tuple(coupler_route.entity_ids),
        channel_order=tuple(coupler_route.product_axis_order),
        samples=np.asarray(samples + 0.0j, dtype=np.complex128),
    )


def build_simultaneous_rabi_gate_sequence(
    *,
    qubits: Sequence[str | sc.EntityRef],
    length: sc.Quantity,
    amplitude: sc.Quantity,
    frequency: sc.Quantity,
) -> RabiGateSequence:
    return RabiGateSequence(
        gates=tuple(
            RabiGate(
                name="x90",
                qubit=qubit,
                length=length,
                amplitude=amplitude,
                frequency=frequency,
            )
            for qubit in _entity_ids(qubits)
        ),
        compiler_id="quantum_lab_demo.experiments.simultaneous_rabi_sequence.v1",
    )


def render_rabi_waveforms(
    *,
    program: RabiGateSequence,
    drive_route: sc.ResolvedRoute,
) -> RenderedWaveformBundle:
    sequence = program
    gate = sequence.gates[0]
    samples = _render_drag_like_envelope(gate.length, gate.amplitude)
    return RenderedWaveformBundle(
        source_program_id=sequence.compiler_id,
        resource_id=drive_route.resource_id,
        entity_ids=tuple(drive_route.entity_ids),
        channel_order=tuple(drive_route.product_axis_order),
        sample_rate_hz=1.0e9,
        samples=samples,
    )


def render_simultaneous_rabi_waveforms(
    *,
    program: RabiGateSequence,
    drive_route: sc.ResolvedRoute,
) -> RenderedWaveformBundle:
    if not program.gates:
        msg = "simultaneous Rabi sequence must contain at least one gate"
        raise ValueError(msg)
    samples = np.vstack(
        [
            _render_drag_like_envelope(gate.length, gate.amplitude)
            for gate in program.gates
        ]
    )
    return RenderedWaveformBundle(
        source_program_id=program.compiler_id,
        resource_id=drive_route.resource_id,
        entity_ids=tuple(drive_route.entity_ids),
        channel_order=tuple(drive_route.product_axis_order),
        sample_rate_hz=1.0e9,
        samples=np.asarray(samples, dtype=np.complex128),
    )


def build_cz_chevron_program(
    *,
    control_qubit: object,
    partner_qubit: object,
    coupler: object,
    duration: object,
    amplitude: object,
    control_echo_amplitude: object,
    partner_echo_amplitude: object,
    coupler_parking_flux: object,
    sample_rate_hz: object,
    control_drive_frequency: object,
    partner_drive_frequency: object,
) -> CzChevronProgram:
    resolved_control_qubit = _required_str(control_qubit, "control_qubit")
    resolved_partner_qubit = _required_str(partner_qubit, "partner_qubit")
    resolved_coupler = _required_str(coupler, "coupler")
    resolved_duration = _required_quantity(duration, "duration")
    resolved_amplitude = _required_quantity(amplitude, "amplitude")
    return CzChevronProgram(
        control_qubit=resolved_control_qubit,
        partner_qubit=resolved_partner_qubit,
        coupler=resolved_coupler,
        drive_pulses=(
            CzDrivePulse(
                qubit=resolved_control_qubit,
                amplitude=_required_quantity(
                    control_echo_amplitude,
                    "control_echo_amplitude",
                ),
                frequency=_required_quantity(
                    control_drive_frequency,
                    "control_drive_frequency",
                ),
            ),
            CzDrivePulse(
                qubit=resolved_partner_qubit,
                amplitude=_required_quantity(
                    partner_echo_amplitude,
                    "partner_echo_amplitude",
                ),
                frequency=_required_quantity(
                    partner_drive_frequency,
                    "partner_drive_frequency",
                ),
            ),
        ),
        coupler_pulse=CzCouplerPulse(
            coupler=resolved_coupler,
            duration=resolved_duration,
            amplitude=resolved_amplitude,
            parking_flux=_required_quantity(
                coupler_parking_flux,
                "coupler_parking_flux",
            ),
        ),
        sample_rate_hz=_required_float(sample_rate_hz, "sample_rate_hz"),
        compiler_id="quantum_lab_demo.experiments.cz_chevron.v1",
        parameters=(QUBIT_PARAMETER_TABLE, TWO_QUBIT_GATE_PARAMETER_TABLE),
    )


def render_cz_drive_waveforms(
    *,
    program: CzChevronProgram,
    drive_route: sc.ResolvedRoute,
) -> RenderedWaveformBundle:
    samples = np.vstack(
        [
            _render_drag_like_envelope(
                program.coupler_pulse.duration,
                pulse.amplitude,
            )
            for pulse in program.drive_pulses
        ]
    )
    return RenderedWaveformBundle(
        source_program_id=program.compiler_id,
        resource_id=drive_route.resource_id,
        entity_ids=tuple(drive_route.entity_ids),
        channel_order=tuple(drive_route.product_axis_order),
        sample_rate_hz=program.sample_rate_hz,
        samples=np.asarray(samples, dtype=np.complex128),
    )


def render_cz_coupler_waveforms(
    *,
    program: CzChevronProgram,
    coupler_route: sc.ResolvedRoute,
) -> RenderedWaveformBundle:
    count = max(8, round(program.coupler_pulse.duration.value))
    plateau = np.full(
        count,
        program.coupler_pulse.amplitude.value,
        dtype=np.float64,
    )
    plateau += program.coupler_pulse.parking_flux.value
    edge = max(2, count // 8)
    ramp = np.sin(np.linspace(0.0, np.pi / 2.0, edge, dtype=np.float64)) ** 2
    plateau[:edge] *= ramp
    plateau[-edge:] *= ramp[::-1]
    return RenderedWaveformBundle(
        source_program_id=program.compiler_id,
        resource_id=coupler_route.resource_id,
        entity_ids=tuple(coupler_route.entity_ids),
        channel_order=tuple(coupler_route.product_axis_order),
        sample_rate_hz=1.0e9,
        samples=np.asarray(plateau + 0.0j, dtype=np.complex128),
    )


def build_parallel_gate_set_program(
    *,
    gates: Sequence[Mapping[str, object]],
    gate_duration: sc.Quantity,
) -> ParallelGateSetProgram:
    duration = _required_quantity(gate_duration, "gate_duration")
    selected: list[ParallelCzGate] = []
    used_qubits: set[str] = set()
    used_couplers: set[str] = set()
    for index, row in enumerate(gates):
        path = f"gates[{index}]"
        control_qubit = _required_str(row.get("control_qubit"), f"{path}.control")
        partner_qubit = _required_str(row.get("partner_qubit"), f"{path}.partner")
        coupler = _required_str(row.get("coupler"), f"{path}.coupler")
        if control_qubit == partner_qubit:
            msg = f"parallel gate {index} must use two distinct qubits"
            raise ValueError(msg)
        overlap = used_qubits.intersection((control_qubit, partner_qubit))
        if overlap:
            msg = "parallel gates must use disjoint qubits: " + ", ".join(
                sorted(overlap)
            )
            raise ValueError(msg)
        if coupler in used_couplers:
            msg = f"parallel gates must use distinct couplers: {coupler}"
            raise ValueError(msg)
        used_qubits.update((control_qubit, partner_qubit))
        used_couplers.add(coupler)
        selected.append(
            ParallelCzGate(
                control_qubit=control_qubit,
                partner_qubit=partner_qubit,
                coupler=coupler,
                duration=duration,
                amplitude=_row_quantity(row, "coupler_parking_flux", path),
                control_frequency=_row_quantity(row, "control_frequency", path),
                partner_frequency=_row_quantity(row, "partner_frequency", path),
            )
        )
    if not selected:
        msg = "parallel gate set requires at least one gate"
        raise ValueError(msg)
    return ParallelGateSetProgram(
        gates=tuple(selected),
        compiler_id="quantum_lab_demo.experiments.parallel_gate_set.v1",
        parameters=(QUBIT_PARAMETER_TABLE, TWO_QUBIT_GATE_PARAMETER_TABLE),
    )


def render_parallel_gate_drive_waveforms(
    *,
    program: ParallelGateSetProgram,
    drive_route: sc.ResolvedRoute,
) -> RenderedWaveformBundle:
    samples = np.vstack(
        [
            _render_drag_like_envelope(
                gate.duration,
                sc.Quantity(value=0.08, unit="arb"),
            )
            for gate in program.gates
            for _ in (gate.control_qubit, gate.partner_qubit)
        ]
    )
    return RenderedWaveformBundle(
        source_program_id=program.compiler_id,
        resource_id=drive_route.resource_id,
        entity_ids=tuple(drive_route.entity_ids),
        channel_order=tuple(drive_route.product_axis_order),
        sample_rate_hz=1.0e9,
        samples=np.asarray(samples, dtype=np.complex128),
    )


def render_parallel_gate_coupler_waveforms(
    *,
    program: ParallelGateSetProgram,
    coupler_route: sc.ResolvedRoute,
) -> RenderedWaveformBundle:
    samples = np.vstack(
        [
            np.asarray(
                np.full(max(8, round(gate.duration.value)), gate.amplitude.value)
                + 0.0j,
                dtype=np.complex128,
            )
            for gate in program.gates
        ]
    )
    return RenderedWaveformBundle(
        source_program_id=program.compiler_id,
        resource_id=coupler_route.resource_id,
        entity_ids=tuple(coupler_route.entity_ids),
        channel_order=tuple(coupler_route.product_axis_order),
        sample_rate_hz=1.0e9,
        samples=np.asarray(samples, dtype=np.complex128),
    )


def build_surface_code_round_program(
    *,
    patch_qubits: Sequence[str | sc.EntityRef],
    data_qubits: Sequence[str | sc.EntityRef],
    ancilla_qubits: Sequence[str | sc.EntityRef],
    couplers: Sequence[str | sc.EntityRef],
    rounds: int,
    cycle_time: sc.Quantity,
) -> SurfaceCodeRoundProgram:
    data = _entity_ids(data_qubits)
    ancilla = _entity_ids(ancilla_qubits)
    coupler_ids = _entity_ids(couplers)
    schedule = tuple(
        f"round-{round_index}:{ancilla_id}->" + ",".join(data)
        for round_index in range(_required_int(rounds, "rounds"))
        for ancilla_id in ancilla
    )
    return SurfaceCodeRoundProgram(
        patch_qubits=_entity_ids(patch_qubits),
        data_qubits=data,
        ancilla_qubits=ancilla,
        couplers=coupler_ids,
        rounds=_required_int(rounds, "rounds"),
        cycle_time=cycle_time,
        schedule=schedule,
        compiler_id="quantum_lab_demo.experiments.surface_code_round.v1",
    )


def render_surface_code_drive_waveforms(
    *,
    program: SurfaceCodeRoundProgram,
    drive_route: sc.ResolvedRoute,
) -> RenderedWaveformBundle:
    samples = np.vstack(
        [
            _render_drag_like_envelope(
                program.cycle_time,
                sc.Quantity(value=0.04, unit="arb"),
            )
            for _ in drive_route.product_axis_order
        ]
    )
    return RenderedWaveformBundle(
        source_program_id=program.compiler_id,
        resource_id=drive_route.resource_id,
        entity_ids=tuple(drive_route.entity_ids),
        channel_order=tuple(drive_route.product_axis_order),
        sample_rate_hz=1.0e9,
        samples=np.asarray(samples, dtype=np.complex128),
    )


def render_surface_code_coupler_waveforms(
    *,
    program: SurfaceCodeRoundProgram,
    coupler_route: sc.ResolvedRoute,
) -> RenderedWaveformBundle:
    count = max(8, round(program.cycle_time.value))
    samples = np.vstack(
        [
            np.asarray(
                0.03 * np.sin(np.linspace(0.0, np.pi, count, dtype=np.float64)) + 0.0j,
                dtype=np.complex128,
            )
            for _ in coupler_route.product_axis_order
        ]
    )
    return RenderedWaveformBundle(
        source_program_id=program.compiler_id,
        resource_id=coupler_route.resource_id,
        entity_ids=tuple(coupler_route.entity_ids),
        channel_order=tuple(coupler_route.product_axis_order),
        sample_rate_hz=1.0e9,
        samples=np.asarray(samples, dtype=np.complex128),
    )


def build_repeated_measurement_program(
    *,
    qubit: str | sc.EntityRef,
    rounds: int,
    shots: int,
    readout_frequency: sc.Quantity,
) -> RepeatedMeasurementProgram:
    return RepeatedMeasurementProgram(
        qubit=_required_str(qubit, "qubit"),
        rounds=_required_int(rounds, "rounds"),
        shots=_required_int(shots, "shots"),
        readout_frequency=readout_frequency,
        compiler_id="quantum_lab_demo.experiments.repeated_measurement.v1",
    )


def build_backend_batch_job(
    *,
    logical_points: int,
    seed: int,
) -> BackendBatchJob:
    point_count = _required_int(logical_points, "logical_points")
    rng = np.random.default_rng(_required_int(seed, "seed"))
    permutation = cast(
        "Sequence[SupportsInt]",
        cast("object", rng.permutation(point_count)),
    )
    returned_order = tuple(int(index) for index in permutation)
    return BackendBatchJob(
        logical_points=point_count,
        submitted_point_uids=tuple(
            f"backend-point-{index}" for index in range(point_count)
        ),
        returned_order=returned_order,
        seed=_required_int(seed, "seed"),
        compiler_id="quantum_lab_demo.experiments.backend_batch.v1",
    )


def _required_str(value: object, name: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, sc.EntityRef):
        return value.id
    msg = f"{name} must resolve to a string, got {value!r}"
    raise TypeError(msg)


def _required_quantity(value: object, name: str) -> sc.Quantity:
    if isinstance(value, sc.Quantity):
        return value
    msg = f"{name} must resolve to a Quantity, got {value!r}"
    raise TypeError(msg)


def _required_int(value: object, name: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    msg = f"{name} must resolve to an integer, got {value!r}"
    raise TypeError(msg)


def _required_float(value: object, name: str) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    msg = f"{name} must resolve to a number, got {value!r}"
    raise TypeError(msg)


def _row_quantity(row: Mapping[str, object], column: str, table_id: str) -> sc.Quantity:
    value = row.get(column)
    if isinstance(value, sc.Quantity):
        return value
    msg = f"{table_id}.{column} must resolve to a Quantity, got {value!r}"
    raise TypeError(msg)


def _render_drag_like_envelope(
    length: sc.Quantity,
    amplitude: sc.Quantity,
) -> NDArray[np.complex128]:
    count = max(8, round(length.value))
    t = np.linspace(-1.0, 1.0, count, dtype=np.float64)
    sigma = 0.35
    gaussian = np.exp(-0.5 * (t / sigma) ** 2)
    derivative = -t / (sigma**2) * gaussian
    envelope = amplitude.value * (gaussian + 0.18j * derivative)
    return np.asarray(envelope, dtype=np.complex128)


def _entity_ids(value: Sequence[str | sc.EntityRef]) -> tuple[str, ...]:
    return tuple(_required_str(item, "entity") for item in value)


__all__ = [
    "build_backend_batch_job",
    "build_cz_chevron_program",
    "build_cz_rb_sequence",
    "build_multiplexed_readout_program",
    "build_parallel_gate_set_program",
    "build_rabi_gate_sequence",
    "build_readout_program",
    "build_repeated_measurement_program",
    "build_simultaneous_rabi_gate_sequence",
    "build_sqg_rb_sequence",
    "build_surface_code_round_program",
    "render_cz_coupler_waveforms",
    "render_cz_drive_waveforms",
    "render_cz_rb_coupler_pulse",
    "render_parallel_gate_coupler_waveforms",
    "render_parallel_gate_drive_waveforms",
    "render_rabi_waveforms",
    "render_simultaneous_rabi_waveforms",
    "render_sqg_rb_pulse_program",
    "render_surface_code_coupler_waveforms",
    "render_surface_code_drive_waveforms",
]

"""One escape hatch for passing a collection without a domain compiler."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, cast

import numpy as np
import scopecat as sc
from numpy.typing import NDArray

from quantum_lab_demo.virtual_lab.parameters import (
    TWO_QUBIT_GATE_PARAMETER_TABLE,
    two_qubit_gate_parameters,
)

PARALLEL_GATE_SET_TEMPLATE_ID = "quantum_lab_demo.scenarios.parallel_gate_set"
_QUBIT = sc.ScalarType(sc.EntityType(entity_kind="logical_qubit"))
_COUPLER = sc.ScalarType(sc.EntityType(entity_kind="logical_coupler"))
_QUANTITY = sc.ScalarType(sc.QuantityType())
_NON_EMPTY_STRING = sc.ScalarType(sc.StringType(min_length=1))
_QUBIT_SERIES = sc.SeriesType(_QUBIT)
_COUPLER_SERIES = sc.SeriesType(_COUPLER)
PARALLEL_GATE_TABLE_TYPE = sc.TableType(
    columns=(
        sc.TableColumn("control_qubit", _QUBIT),
        sc.TableColumn("partner_qubit", _QUBIT),
        sc.TableColumn("gate", _NON_EMPTY_STRING),
    ),
    primary_key=("control_qubit", "partner_qubit", "gate"),
    min_rows=1,
)
GATE_DURATION = sc.coordinate("gate_duration", _QUANTITY)
_DEFAULT_GATES = (
    {"control_qubit": "q0", "partner_qubit": "q1", "gate": "cz"},
    {"control_qubit": "q2", "partner_qubit": "q3", "gate": "cz"},
)
_DEFAULT_QUBITS = ("q0", "q1", "q2", "q3")
_DEFAULT_COUPLERS = ("coupler-q0-q1", "coupler-q2-q3")


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


@dataclass(frozen=True)
class ParallelGateSetProgram:
    gates: tuple[ParallelCzGate, ...]
    compiler_id: str
    parameters: tuple[str, ...]


def build_parallel_gate_set_program(
    *,
    gates: Sequence[Mapping[str, object]],
    gate_parameters: Sequence[Mapping[str, object]],
    gate_duration: sc.Quantity,
    qubits: Sequence[object],
    couplers: Sequence[object],
) -> ParallelGateSetProgram:
    """Resolve one opaque collection and verify its precomputed footprint."""

    parameters_by_gate = {_gate_key(row): row for row in gate_parameters}
    selected = tuple(
        ParallelCzGate(
            control_qubit=_entity_id(row["control_qubit"]),
            partner_qubit=_entity_id(row["partner_qubit"]),
            coupler=_entity_id(parameters_by_gate[_gate_key(row)]["coupler"]),
            duration=gate_duration,
            amplitude=cast(
                "sc.Quantity",
                parameters_by_gate[_gate_key(row)]["coupler_parking_flux"],
            ),
        )
        for row in gates
    )
    _require_matching_footprint(selected, qubits=qubits, couplers=couplers)
    return ParallelGateSetProgram(
        gates=selected,
        compiler_id="quantum_lab_demo.scenarios.parallel_gate_set.v1",
        parameters=(TWO_QUBIT_GATE_PARAMETER_TABLE,),
    )


def render_parallel_gate_drive_waveforms(
    *, program: ParallelGateSetProgram
) -> RenderedWaveformBundle:
    samples = np.vstack(
        [
            _render_drag_like_envelope(gate.duration, sc.Quantity(0.08, "arb"))
            for gate in program.gates
            for _ in (gate.control_qubit, gate.partner_qubit)
        ]
    )
    return RenderedWaveformBundle(
        source_program_id=program.compiler_id,
        entity_ids=tuple(
            qubit
            for gate in program.gates
            for qubit in (gate.control_qubit, gate.partner_qubit)
        ),
        sample_rate_hz=1.0e9,
        samples=np.asarray(samples, dtype=np.complex128),
    )


def render_parallel_gate_coupler_waveforms(
    *, program: ParallelGateSetProgram
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
        entity_ids=tuple(gate.coupler for gate in program.gates),
        sample_rate_hz=1.0e9,
        samples=np.asarray(samples, dtype=np.complex128),
    )


def _entity_id(value: object) -> str:
    return value.id if isinstance(value, sc.EntityRef) else cast("str", value)


def _gate_key(row: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        _entity_id(row["control_qubit"]),
        _entity_id(row["partner_qubit"]),
        cast("str", row["gate"]),
    )


def _require_matching_footprint(
    gates: Sequence[ParallelCzGate],
    *,
    qubits: Sequence[object],
    couplers: Sequence[object],
) -> None:
    expected_qubits = {
        qubit for gate in gates for qubit in (gate.control_qubit, gate.partner_qubit)
    }
    if {_entity_id(qubit) for qubit in qubits} != expected_qubits:
        msg = "explicit qubit footprint does not match the compiled gate collection"
        raise ValueError(msg)
    if {_entity_id(coupler) for coupler in couplers} != {
        gate.coupler for gate in gates
    }:
        msg = "explicit coupler footprint does not match the compiled gate collection"
        raise ValueError(msg)


def _render_drag_like_envelope(
    length: sc.Quantity, amplitude: sc.Quantity
) -> NDArray[np.complex128]:
    time = np.linspace(-1.0, 1.0, max(8, round(length.value)), dtype=np.float64)
    gaussian = np.exp(-0.5 * (time / 0.35) ** 2)
    derivative = -time / (0.35**2) * gaussian
    return np.asarray(
        amplitude.value * (gaussian + 0.18j * derivative),
        dtype=np.complex128,
    )


@sc.module(id="quantum_lab_demo.scenarios.two_qubit.parallel_gate_set")
def _parallel_gate_set_module(
    gates: Annotated[sc.Input[tuple[dict[str, str], ...]], PARALLEL_GATE_TABLE_TYPE],
    qubits: Annotated[sc.Input[tuple[str, ...]], _QUBIT_SERIES],
    couplers: Annotated[sc.Input[tuple[str, ...]], _COUPLER_SERIES],
):
    gates_ref = sc.input_ref(gates)
    # Routing precedes opaque compute, so its entity footprint stays explicit.
    qubits_ref = sc.input_ref(qubits)
    couplers_ref = sc.input_ref(couplers)
    build_program = sc.compute(
        "build-parallel-gate-set-program",
        fn=build_parallel_gate_set_program,
        output_type=sc.ScalarType(sc.PayloadType("gate_sequence")),
        inputs={
            # This is the escape hatch being demonstrated: the collection remains
            # one compute input instead of expanding into experiment points.
            "gates": gates_ref,
            "gate_parameters": two_qubit_gate_parameters(),
            "gate_duration": GATE_DURATION,
            "qubits": qubits_ref,
            "couplers": couplers_ref,
        },
    )
    drive_waveforms = sc.compute(
        "render-parallel-gate-drive-waveforms",
        fn=render_parallel_gate_drive_waveforms,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={"program": build_program.output},
    )
    coupler_waveforms = sc.compute(
        "render-parallel-gate-coupler-waveforms",
        fn=render_parallel_gate_coupler_waveforms,
        output_type=sc.ScalarType(sc.PayloadType("pulse_program")),
        inputs={"program": build_program.output},
    )
    return (
        sc.module_body()
        .resource(
            "drive",
            requires=("play_gate_sequence", "play_pulse_program"),
            for_entities=(qubits_ref,),
        )
        .resource(
            "coupler",
            requires=("play_coupler_pulse",),
            for_entities=(couplers_ref,),
        )
        .computes(build_program, drive_waveforms, coupler_waveforms)
        .bind_field(
            "drive",
            capability="play_gate_sequence",
            field="sequence",
            value=build_program.output,
        )
        .bind_field(
            "drive",
            capability="play_pulse_program",
            field="program",
            value=drive_waveforms.output,
        )
        .bind_field(
            "coupler",
            capability="play_coupler_pulse",
            field="program",
            value=coupler_waveforms.output,
        )
    )


@sc.module(id="quantum_lab_demo.scenarios.readout.collection_capture")
def _collection_readout_module(
    qubits: Annotated[sc.Input[tuple[str, ...]], _QUBIT_SERIES],
):
    qubits_ref = sc.input_ref(qubits)
    return (
        sc.module_body()
        .resource("readout", requires=("acquire_iq",), for_entities=(qubits_ref,))
        .bind_field(
            "readout",
            capability="acquire_iq",
            field="repetitions",
            value=sc.parameter("repetitions", _QUANTITY),
        )
        .product(
            "multiplexed_iq",
            unit="ratio",
            dtype="complex128",
            axes=(sc.entity_axis("qubit", qubits_ref),),
        )
        .acquire(
            "read-multiplexed-iq",
            "multiplexed_iq",
            resource="readout",
            capability="acquire_iq",
        )
    )


@sc.template(
    id=PARALLEL_GATE_SET_TEMPLATE_ID,
    kind="parallel_gate_set",
)
def parallel_gate_set_template(
    gates: Annotated[
        sc.Input[tuple[dict[str, str], ...]], PARALLEL_GATE_TABLE_TYPE
    ] = _DEFAULT_GATES,
    qubits: Annotated[sc.Input[tuple[str, ...]], _QUBIT_SERIES] = _DEFAULT_QUBITS,
    couplers: Annotated[sc.Input[tuple[str, ...]], _COUPLER_SERIES] = _DEFAULT_COUPLERS,
) -> sc.ExperimentBody:
    gate_set = _parallel_gate_set_module(
        gates=gates,
        qubits=qubits,
        couplers=couplers,
    )
    readout = _collection_readout_module.instantiate(
        "parallel-readout",
        qubits=qubits,
    )
    return (
        sc.experiment(gate_set, readout)
        .scan(GATE_DURATION, (28, 36), unit="ns")
        .record_product(readout.products.multiplexed_iq)
    )


__all__ = [
    "GATE_DURATION",
    "PARALLEL_GATE_SET_TEMPLATE_ID",
    "PARALLEL_GATE_TABLE_TYPE",
    "ParallelCzGate",
    "ParallelGateSetProgram",
    "RenderedWaveformBundle",
    "build_parallel_gate_set_program",
    "parallel_gate_set_template",
]

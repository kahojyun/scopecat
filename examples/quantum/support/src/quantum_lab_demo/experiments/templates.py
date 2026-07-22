"""Experiment-system template entrypoints."""

from __future__ import annotations

from typing import Annotated, cast

import scopecat as sc

from quantum_lab_demo.experiments.backend_modules import BACKEND_BATCH_MODULE
from quantum_lab_demo.experiments.background_modules import (
    FLUX_BACKGROUND_MODULE,
    SPECTATOR_FLUX_BACKGROUND_MODULE,
    SYSTEM_COUPLER_PARKING_BACKGROUND_MODULE,
)
from quantum_lab_demo.experiments.ids import (
    BACKEND_BATCH_TEMPLATE_ID,
    CZ_CHEVRON_TEMPLATE_ID,
    CZ_RB_TEMPLATE_ID,
    FLUX_BACKGROUND_RABI_TEMPLATE_ID,
    MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE_ID,
    MULTIPLEXED_READOUT_TEMPLATE_ID,
    PARALLEL_GATE_SET_TEMPLATE_ID,
    QND_REPEATED_MEASUREMENT_TEMPLATE_ID,
    RABI_TEMPLATE_ID,
    READOUT_TEMPLATE_ID,
    SIMULTANEOUS_RABI_TEMPLATE_ID,
    SPECTATOR_CZ_TEMPLATE_ID,
    SQG_RB_TEMPLATE_ID,
    SYSTEM_BACKGROUND_RABI_TEMPLATE_ID,
    TOY_SURFACE_CODE_ROUND_TEMPLATE_ID,
)
from quantum_lab_demo.experiments.parameter_refs import qubit_param
from quantum_lab_demo.experiments.points import (
    CLIFFORD_COUNT,
    COUPLER_AMPLITUDE,
    COUPLER_DURATION,
    DRIVE_LENGTH,
    GATE_DURATION,
    READOUT_FREQUENCY,
)
from quantum_lab_demo.experiments.rabi_modules import (
    RABI_MODULE,
    SIMULTANEOUS_RABI_MODULE,
)
from quantum_lab_demo.experiments.rb_modules import CZ_RB_MODULE, SQG_RB_MODULE
from quantum_lab_demo.experiments.readout_modules import (
    MULTIPLEXED_READOUT_MODULE,
    MULTIPLEXED_READOUT_PULSE_MODULE,
    QND_REPEATED_MEASUREMENT_MODULE,
    READOUT_CAPTURE_MODULE,
    READOUT_MODULE,
)
from quantum_lab_demo.experiments.surface_code_modules import (
    TOY_SURFACE_CODE_ROUND_MODULE,
)
from quantum_lab_demo.experiments.two_qubit_modules import (
    CZ_CHEVRON_MODULE,
    PARALLEL_GATE_QUBITS,
    PARALLEL_GATE_SET_MODULE,
)

_QUBIT = sc.ScalarType(sc.EntityType(entity_kind="logical_qubit"))
_COUPLER = sc.ScalarType(sc.EntityType(entity_kind="logical_coupler"))
_QUBIT_SERIES = sc.SeriesType(_QUBIT)
_COUPLER_SERIES = sc.SeriesType(_COUPLER)
_QUANTITY = sc.ScalarType(sc.QuantityType())
_NON_NEGATIVE_INT = sc.ScalarType(sc.IntType(minimum=0))
_POSITIVE_INT = sc.ScalarType(sc.IntType(minimum=1))
_NON_EMPTY_STRING = sc.ScalarType(sc.StringType(min_length=1))
_PARALLEL_GATE_TABLE = sc.TableType(
    columns=(
        sc.TableColumn("control_qubit", _QUBIT),
        sc.TableColumn("partner_qubit", _QUBIT),
        sc.TableColumn("gate", _NON_EMPTY_STRING),
    ),
    primary_key=("control_qubit", "partner_qubit", "gate"),
    min_rows=1,
)
_CENTER_LENGTH_DEFAULT = sc.Quantity(value=48.0, unit="ns")
_DRIVE_AMPLITUDE_DEFAULT = sc.Quantity(value=0.28, unit="arb")
_DRIVE_FREQUENCY_DEFAULT = sc.Quantity(value=5.1, unit="GHz")
_FLUX_BIAS_DEFAULT = sc.Quantity(value=0.06, unit="arb")
_CENTER_FREQUENCY_DEFAULT = sc.Quantity(value=6.6, unit="GHz")
_READOUT_POWER_DEFAULT = sc.Quantity(value=-20.5, unit="dBm")
_SPECTATOR_FLUX_BIAS_DEFAULT = sc.Quantity(value=0.025, unit="arb")
_CYCLE_TIME_DEFAULT = sc.Quantity(value=32.0, unit="ns")
_PARALLEL_GATES_DEFAULT = (
    {
        "control_qubit": "q0",
        "partner_qubit": "q1",
        "gate": "cz",
    },
    {
        "control_qubit": "q2",
        "partner_qubit": "q3",
        "gate": "cz",
    },
)


@sc.template(id=RABI_TEMPLATE_ID, kind="rabi", label="Rabi")
def RABI_TEMPLATE(
    qubit: Annotated[sc.Input[str], _QUBIT],
) -> sc.ExperimentBody:
    """Build a experiment-system single-qubit Rabi length scan."""

    rabi = RABI_MODULE(qubit=qubit)
    capture = READOUT_CAPTURE_MODULE()
    return (
        sc.experiment(rabi, capture)
        .scan(
            DRIVE_LENGTH,
            center=qubit_param("rabi_pulse_length", cast("sc.ValueRef", qubit)),
            span=sc.Quantity(value=80.0, unit="ns"),
            points=5,
        )
        .record_product(capture.products.probability_1, record_id="probability_1")
        .record_product(capture.products.raw_iq, record_id="raw_iq")
    )


@sc.template(
    id=SIMULTANEOUS_RABI_TEMPLATE_ID,
    kind="simultaneous_rabi",
    label="simultaneous Rabi",
)
def SIMULTANEOUS_RABI_TEMPLATE(
    qubits: Annotated[sc.Input[tuple[str, ...]], _QUBIT_SERIES] = ("q0", "q1"),
    center_length: Annotated[sc.Input[sc.Quantity], _QUANTITY] = _CENTER_LENGTH_DEFAULT,
    drive_amplitude: Annotated[
        sc.Input[sc.Quantity], _QUANTITY
    ] = _DRIVE_AMPLITUDE_DEFAULT,
    drive_frequency: Annotated[
        sc.Input[sc.Quantity], _QUANTITY
    ] = _DRIVE_FREQUENCY_DEFAULT,
) -> sc.ExperimentBody:
    """Build a simultaneous multi-qubit Rabi scan with array readout."""

    rabi = SIMULTANEOUS_RABI_MODULE(
        qubits=qubits,
        drive_amplitude=drive_amplitude,
        drive_frequency=drive_frequency,
    )
    readout = MULTIPLEXED_READOUT_MODULE(qubits=qubits)
    return (
        sc.experiment(rabi, readout)
        .scan(
            DRIVE_LENGTH,
            center=center_length,
            span=sc.Quantity(value=60.0, unit="ns"),
            points=5,
        )
        .record_product(readout.products.multiplexed_iq, record_id="multiplexed_iq")
    )


@sc.template(
    id=FLUX_BACKGROUND_RABI_TEMPLATE_ID,
    kind="flux_background_rabi",
    label="flux-background Rabi",
)
def FLUX_BACKGROUND_RABI_TEMPLATE(
    qubit: Annotated[sc.Input[str], _QUBIT],
    coupler: Annotated[sc.Input[str], _COUPLER] = "coupler-q0-q1",
    flux_bias: Annotated[sc.Input[sc.Quantity], _QUANTITY] = _FLUX_BIAS_DEFAULT,
) -> sc.ExperimentBody:
    """Build a Rabi scan while holding a coupler flux-bias background."""

    background = FLUX_BACKGROUND_MODULE(coupler=coupler, flux_bias=flux_bias)
    rabi = RABI_MODULE(qubit=qubit)
    capture = READOUT_CAPTURE_MODULE()
    return (
        sc.experiment(background, rabi, capture)
        .scan(
            DRIVE_LENGTH,
            center=qubit_param("rabi_pulse_length", cast("sc.ValueRef", qubit)),
            span=sc.Quantity(value=80.0, unit="ns"),
            points=5,
        )
        .record_product(capture.products.probability_1, record_id="probability_1")
        .record_product(capture.products.raw_iq, record_id="raw_iq")
    )


@sc.template(
    id=SYSTEM_BACKGROUND_RABI_TEMPLATE_ID,
    kind="system_background_rabi",
    label="parameter-table background Rabi",
    description=(
        "Build a Rabi scan while materializing all coupler parking flux "
        "background outputs from the accepted two-qubit gate parameter table."
    ),
)
def SYSTEM_BACKGROUND_RABI_TEMPLATE(
    qubit: Annotated[sc.Input[str], _QUBIT],
) -> sc.ExperimentBody:
    background = SYSTEM_COUPLER_PARKING_BACKGROUND_MODULE()
    rabi = RABI_MODULE(qubit=qubit)
    capture = READOUT_CAPTURE_MODULE()
    return (
        sc.experiment(background, rabi, capture)
        .scan(
            DRIVE_LENGTH,
            center=qubit_param("rabi_pulse_length", cast("sc.ValueRef", qubit)),
            span=sc.Quantity(value=80.0, unit="ns"),
            points=5,
        )
        .record_product(capture.products.probability_1, record_id="probability_1")
        .record_product(capture.products.raw_iq, record_id="raw_iq")
    )


@sc.template(
    id=READOUT_TEMPLATE_ID, kind="readout_frequency", label="readout frequency"
)
def READOUT_TEMPLATE(
    qubit: Annotated[sc.Input[str], _QUBIT],
) -> sc.ExperimentBody:
    """Build a experiment-system readout frequency scan."""

    readout = READOUT_MODULE(qubit=qubit)
    return (
        sc.experiment(readout)
        .scan(
            READOUT_FREQUENCY,
            center=qubit_param("readout_frequency", cast("sc.ValueRef", qubit)),
            span=sc.Quantity(value=100.0, unit="MHz"),
            points=5,
        )
        .record_product(readout.products.raw_iq, record_id="raw_iq")
        .record_product(readout.products.state0_iq, record_id="state0_iq")
        .record_product(readout.products.state1_iq, record_id="state1_iq")
        .record_product(
            readout.products.state0_iq_stdev,
            record_id="state0_iq_stdev",
        )
        .record_product(
            readout.products.state1_iq_stdev,
            record_id="state1_iq_stdev",
        )
    )


@sc.template(
    id=MULTIPLEXED_READOUT_TEMPLATE_ID,
    kind="multiplexed_readout",
    label="multiplexed readout",
)
def MULTIPLEXED_READOUT_TEMPLATE(
    qubits: Annotated[sc.Input[tuple[str, ...]], _QUBIT_SERIES] = ("q0", "q1"),
) -> sc.ExperimentBody:
    """Build a simultaneous readout over an entity series."""

    readout = MULTIPLEXED_READOUT_MODULE(qubits=qubits)
    return sc.experiment(readout).record_product(
        readout.products.multiplexed_iq,
        record_id="multiplexed_iq",
    )


@sc.template(
    id=MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE_ID,
    kind="multiplexed_readout_calibration",
    label="multiplexed readout calibration",
)
def MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE(
    qubits: Annotated[sc.Input[tuple[str, ...]], _QUBIT_SERIES] = ("q0", "q1"),
    center_frequency: Annotated[
        sc.Input[sc.Quantity], _QUANTITY
    ] = _CENTER_FREQUENCY_DEFAULT,
    readout_power: Annotated[sc.Input[sc.Quantity], _QUANTITY] = _READOUT_POWER_DEFAULT,
) -> sc.ExperimentBody:
    """Build a shared readout-frequency scan returning an entity series."""

    readout = MULTIPLEXED_READOUT_PULSE_MODULE(
        qubits=qubits,
        readout_power=readout_power,
    )
    return (
        sc.experiment(readout)
        .scan(
            READOUT_FREQUENCY,
            center=center_frequency,
            span=sc.Quantity(value=120.0, unit="MHz"),
            points=5,
        )
        .record_product(readout.products.multiplexed_iq, record_id="multiplexed_iq")
    )


@sc.template(id=SQG_RB_TEMPLATE_ID, kind="sqg_rb", label="SQG RB")
def SQG_RB_TEMPLATE(
    qubit: Annotated[sc.Input[str], _QUBIT],
    seed: Annotated[sc.Input[int], _NON_NEGATIVE_INT] = 0,
) -> sc.ExperimentBody:
    """Build a experiment-system single-qubit randomized benchmarking scan."""

    rb = SQG_RB_MODULE(qubit=qubit, seed=seed)
    capture = READOUT_CAPTURE_MODULE()
    return (
        sc.experiment(rb, capture)
        .scan(CLIFFORD_COUNT, (4, 8, 16))
        .record_product(capture.products.probability_0, record_id="probability_0")
        .record_product(capture.products.probability_1, record_id="probability_1")
        .record_product(capture.products.raw_iq, record_id="raw_iq")
    )


@sc.template(id=CZ_RB_TEMPLATE_ID, kind="cz_rb", label="CZ RB")
def CZ_RB_TEMPLATE(
    control_qubit: Annotated[sc.Input[str], _QUBIT],
    partner_qubit: Annotated[sc.Input[str], _QUBIT],
    coupler: Annotated[sc.Input[str], _COUPLER] = "coupler-q0-q1",
    seed: Annotated[sc.Input[int], _NON_NEGATIVE_INT] = 0,
    interleaved_gate: Annotated[sc.Input[str], _NON_EMPTY_STRING] = "CZ",
) -> sc.ExperimentBody:
    """Build a experiment-system two-qubit CZ randomized benchmarking scan."""

    rb = CZ_RB_MODULE(
        control_qubit=control_qubit,
        partner_qubit=partner_qubit,
        coupler=coupler,
        seed=seed,
        interleaved_gate=interleaved_gate,
    )
    capture = READOUT_CAPTURE_MODULE()
    return (
        sc.experiment(rb, capture)
        .scan(CLIFFORD_COUNT, (2, 4, 8))
        .record_product(capture.products.probability_0, record_id="probability_0")
        .record_product(capture.products.probability_1, record_id="probability_1")
        .record_product(capture.products.raw_iq, record_id="raw_iq")
    )


@sc.template(id=CZ_CHEVRON_TEMPLATE_ID, kind="cz_chevron", label="CZ chevron")
def CZ_CHEVRON_TEMPLATE(
    control_qubit: Annotated[sc.Input[str], _QUBIT],
    partner_qubit: Annotated[sc.Input[str], _QUBIT],
    coupler: Annotated[sc.Input[str], _COUPLER] = "coupler-q0-q1",
) -> sc.ExperimentBody:
    """Build a two-dimensional CZ amplitude-duration calibration scan."""

    chevron = CZ_CHEVRON_MODULE(
        control_qubit=control_qubit,
        partner_qubit=partner_qubit,
        coupler=coupler,
    )
    capture = READOUT_CAPTURE_MODULE()
    return (
        sc.experiment(chevron, capture)
        .scan(COUPLER_DURATION, (24, 36, 48), unit="ns")
        .scan(COUPLER_AMPLITUDE, (0.18, 0.24, 0.30), unit="arb")
        .record_product(capture.products.probability_0, record_id="probability_0")
        .record_product(capture.products.probability_1, record_id="probability_1")
        .record_product(capture.products.raw_iq, record_id="raw_iq")
    )


@sc.template(
    id=SPECTATOR_CZ_TEMPLATE_ID,
    kind="spectator_cz_calibration",
    label="spectator-aware CZ calibration",
    description=(
        "Build a CZ calibration while maintaining explicit spectator "
        "background flux state."
    ),
)
def SPECTATOR_CZ_TEMPLATE(
    control_qubit: Annotated[sc.Input[str], _QUBIT],
    partner_qubit: Annotated[sc.Input[str], _QUBIT],
    coupler: Annotated[sc.Input[str], _COUPLER] = "coupler-q0-q1",
    background_couplers: Annotated[
        sc.Input[tuple[str, ...]],
        _COUPLER_SERIES,
    ] = ("coupler-q2-q3",),
    spectator_flux_bias: Annotated[
        sc.Input[sc.Quantity],
        _QUANTITY,
    ] = _SPECTATOR_FLUX_BIAS_DEFAULT,
) -> sc.ExperimentBody:
    background = SPECTATOR_FLUX_BACKGROUND_MODULE(
        background_couplers=background_couplers,
        spectator_flux_bias=spectator_flux_bias,
    )
    chevron = CZ_CHEVRON_MODULE(
        control_qubit=control_qubit,
        partner_qubit=partner_qubit,
        coupler=coupler,
    )
    capture = READOUT_CAPTURE_MODULE()
    return (
        sc.experiment(background, chevron, capture)
        .scan(COUPLER_DURATION, (24, 36), unit="ns")
        .scan(COUPLER_AMPLITUDE, (0.18, 0.24), unit="arb")
        .record_product(capture.products.probability_0, record_id="probability_0")
        .record_product(capture.products.probability_1, record_id="probability_1")
        .record_product(capture.products.raw_iq, record_id="raw_iq")
    )


@sc.template(
    id=PARALLEL_GATE_SET_TEMPLATE_ID,
    kind="parallel_gate_set",
    label="parallel gate set",
    description=(
        "Pass a table-defined set of disjoint CZ calibrations through the "
        "opaque-payload escape hatch, preserving collection order across "
        "resource fan-out and entity-axis records."
    ),
)
def PARALLEL_GATE_SET_TEMPLATE(
    gates: Annotated[
        sc.Input[tuple[dict[str, str], ...]],
        _PARALLEL_GATE_TABLE,
    ] = _PARALLEL_GATES_DEFAULT,
) -> sc.ExperimentBody:
    gate_set = PARALLEL_GATE_SET_MODULE(gates=gates)
    readout = MULTIPLEXED_READOUT_MODULE.instantiate(
        "parallel-readout",
        qubits=PARALLEL_GATE_QUBITS,
    )
    return (
        sc.experiment(gate_set, readout)
        .scan(GATE_DURATION, (28, 36), unit="ns")
        .record_product(readout.products.multiplexed_iq, record_id="multiplexed_iq")
    )


@sc.template(
    id=TOY_SURFACE_CODE_ROUND_TEMPLATE_ID,
    kind="toy_surface_code_round",
    label="toy surface-code round",
    description=(
        "Build a small stabilizer-round schedule with drive, coupler, and "
        "round-by-entity readout output."
    ),
)
def TOY_SURFACE_CODE_ROUND_TEMPLATE(
    patch_qubits: Annotated[sc.Input[tuple[str, ...]], _QUBIT_SERIES] = (
        "q0",
        "q1",
        "q2",
        "q3",
    ),
    data_qubits: Annotated[sc.Input[tuple[str, ...]], _QUBIT_SERIES] = ("q0", "q1"),
    ancilla_qubits: Annotated[sc.Input[tuple[str, ...]], _QUBIT_SERIES] = (
        "q2",
        "q3",
    ),
    couplers: Annotated[sc.Input[tuple[str, ...]], _COUPLER_SERIES] = (
        "coupler-q0-q1",
        "coupler-q2-q3",
    ),
    rounds: Annotated[sc.Input[int], _POSITIVE_INT] = 3,
    cycle_time: Annotated[sc.Input[sc.Quantity], _QUANTITY] = _CYCLE_TIME_DEFAULT,
) -> sc.ExperimentBody:
    toy_round = TOY_SURFACE_CODE_ROUND_MODULE(
        patch_qubits=patch_qubits,
        data_qubits=data_qubits,
        ancilla_qubits=ancilla_qubits,
        couplers=couplers,
        rounds=rounds,
        cycle_time=cycle_time,
    )
    return sc.experiment(toy_round).record_product(
        toy_round.products.stabilizer_iq,
        record_id="stabilizer_iq",
    )


@sc.template(
    id=QND_REPEATED_MEASUREMENT_TEMPLATE_ID,
    kind="qnd_repeated_measurement",
    label="QND repeated measurement",
)
def QND_REPEATED_MEASUREMENT_TEMPLATE(
    qubit: Annotated[sc.Input[str], _QUBIT],
    rounds: Annotated[sc.Input[int], _POSITIVE_INT] = 4,
    shots: Annotated[sc.Input[int], _POSITIVE_INT] = 16,
) -> sc.ExperimentBody:
    """Build a repeated readout returning one dense round-by-shot array."""

    readout = QND_REPEATED_MEASUREMENT_MODULE(
        qubit=qubit,
        rounds=rounds,
        shots=shots,
    )
    return sc.experiment(readout).record_product(
        readout.products.qnd_iq,
        record_id="qnd_iq",
    )


@sc.template(
    id=BACKEND_BATCH_TEMPLATE_ID,
    kind="backend_batch_out_of_order",
    label="backend batch out-of-order",
    description=(
        "Build a backend-batch mock that keeps logical batch points inside one "
        "array output and records returned order in the compute payload."
    ),
)
def BACKEND_BATCH_TEMPLATE(
    logical_points: Annotated[sc.Input[int], _POSITIVE_INT] = 5,
    seed: Annotated[sc.Input[int], _NON_NEGATIVE_INT] = 7,
) -> sc.ExperimentBody:
    batch = BACKEND_BATCH_MODULE(logical_points=logical_points, seed=seed)
    return sc.experiment(batch).record_product(
        batch.products.backend_probabilities,
        record_id="backend_probabilities",
    )


__all__ = [
    "BACKEND_BATCH_TEMPLATE",
    "BACKEND_BATCH_TEMPLATE_ID",
    "CZ_CHEVRON_TEMPLATE",
    "CZ_CHEVRON_TEMPLATE_ID",
    "CZ_RB_TEMPLATE",
    "CZ_RB_TEMPLATE_ID",
    "FLUX_BACKGROUND_RABI_TEMPLATE",
    "FLUX_BACKGROUND_RABI_TEMPLATE_ID",
    "MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE",
    "MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE_ID",
    "MULTIPLEXED_READOUT_TEMPLATE",
    "MULTIPLEXED_READOUT_TEMPLATE_ID",
    "PARALLEL_GATE_SET_TEMPLATE",
    "PARALLEL_GATE_SET_TEMPLATE_ID",
    "QND_REPEATED_MEASUREMENT_TEMPLATE",
    "QND_REPEATED_MEASUREMENT_TEMPLATE_ID",
    "RABI_TEMPLATE",
    "RABI_TEMPLATE_ID",
    "READOUT_TEMPLATE",
    "READOUT_TEMPLATE_ID",
    "SIMULTANEOUS_RABI_TEMPLATE",
    "SIMULTANEOUS_RABI_TEMPLATE_ID",
    "SPECTATOR_CZ_TEMPLATE",
    "SPECTATOR_CZ_TEMPLATE_ID",
    "SQG_RB_TEMPLATE",
    "SQG_RB_TEMPLATE_ID",
    "SYSTEM_BACKGROUND_RABI_TEMPLATE",
    "SYSTEM_BACKGROUND_RABI_TEMPLATE_ID",
    "TOY_SURFACE_CODE_ROUND_TEMPLATE",
    "TOY_SURFACE_CODE_ROUND_TEMPLATE_ID",
]

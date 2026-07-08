"""Experiment-system template entrypoints."""

from __future__ import annotations

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
from quantum_lab_demo.experiments.record_modules import (
    BACKEND_PROBABILITY_RECORD_MODULE,
    MULTIPLEXED_IQ_RECORD_MODULE,
    PROBABILITY_1_RECORD_MODULE,
    PROBABILITY_RECORDS_MODULE,
    QND_IQ_RECORD_MODULE,
    RAW_IQ_RECORD_MODULE,
    READOUT_CLASSIFICATION_RECORDS_MODULE,
    STABILIZER_IQ_RECORD_MODULE,
)
from quantum_lab_demo.experiments.surface_code_modules import (
    TOY_SURFACE_CODE_ROUND_MODULE,
)
from quantum_lab_demo.experiments.two_qubit_modules import (
    CZ_CHEVRON_MODULE,
    PARALLEL_GATE_SET_MODULE,
)

RABI_TEMPLATE = sc.template(
    id=RABI_TEMPLATE_ID,
    experiment_id="rabi",
    kind="rabi",
    sources=(
        sc.around_points(
            "drive_length",
            center=qubit_param("rabi_pulse_length"),
            default_span=sc.Quantity(value=80.0, unit="ns"),
            points=5,
            input_id="drive_length",
        ),
        RABI_MODULE,
        READOUT_CAPTURE_MODULE,
        PROBABILITY_1_RECORD_MODULE,
        RAW_IQ_RECORD_MODULE,
        sc.record_product("probability_1"),
        sc.record_product("raw_iq"),
    ),
    label="Rabi",
    description="Build a experiment-system single-qubit Rabi length scan.",
    inputs=(
        sc.InputDescription(id="qubit", kind="entity"),
        sc.InputDescription(id="drive_length", kind="quantity"),
    ),
    defaults={"drive_length": None},
    metadata={"category": "rabi"},
)

SIMULTANEOUS_RABI_TEMPLATE = sc.template(
    id=SIMULTANEOUS_RABI_TEMPLATE_ID,
    experiment_id="simultaneous-rabi",
    kind="simultaneous_rabi",
    sources=(
        sc.around_points(
            "drive_length",
            center=sc.input("center_length"),
            default_span=sc.Quantity(value=60.0, unit="ns"),
            points=5,
            input_id="drive_length",
        ),
        SIMULTANEOUS_RABI_MODULE,
        MULTIPLEXED_READOUT_MODULE,
        MULTIPLEXED_IQ_RECORD_MODULE,
        sc.record_product("multiplexed_iq"),
    ),
    label="simultaneous Rabi",
    description="Build a simultaneous multi-qubit Rabi scan with array readout.",
    inputs=(
        sc.InputDescription(
            id="qubits",
            kind="entity_array",
            default=("q0", "q1"),
        ),
        sc.InputDescription(id="drive_length", kind="quantity"),
        sc.InputDescription(
            id="center_length",
            kind="quantity",
            default=sc.Quantity(value=48.0, unit="ns"),
        ),
        sc.InputDescription(
            id="drive_amplitude",
            kind="quantity",
            default=sc.Quantity(value=0.28, unit="arb"),
        ),
        sc.InputDescription(
            id="drive_frequency",
            kind="quantity",
            default=sc.Quantity(value=5.1, unit="GHz"),
        ),
    ),
    defaults={
        "qubits": sc.entity_array(("q0", "q1")),
        "drive_length": None,
        "center_length": sc.Quantity(value=48.0, unit="ns"),
        "drive_amplitude": sc.Quantity(value=0.28, unit="arb"),
        "drive_frequency": sc.Quantity(value=5.1, unit="GHz"),
    },
    metadata={"category": "rabi"},
)

FLUX_BACKGROUND_RABI_TEMPLATE = sc.template(
    id=FLUX_BACKGROUND_RABI_TEMPLATE_ID,
    experiment_id="flux-background-rabi",
    kind="flux_background_rabi",
    sources=(
        sc.around_points(
            "drive_length",
            center=qubit_param("rabi_pulse_length"),
            default_span=sc.Quantity(value=80.0, unit="ns"),
            points=5,
            input_id="drive_length",
        ),
        FLUX_BACKGROUND_MODULE,
        RABI_MODULE,
        READOUT_CAPTURE_MODULE,
        PROBABILITY_1_RECORD_MODULE,
        RAW_IQ_RECORD_MODULE,
        sc.record_product("probability_1"),
        sc.record_product("raw_iq"),
    ),
    label="flux-background Rabi",
    description="Build a Rabi scan while holding a coupler flux-bias background.",
    inputs=(
        sc.InputDescription(id="qubit", kind="entity"),
        sc.InputDescription(
            id="coupler",
            kind="entity",
            default="coupler-q0-q1",
        ),
        sc.InputDescription(id="drive_length", kind="quantity"),
        sc.InputDescription(
            id="flux_bias",
            kind="quantity",
            default=sc.Quantity(value=0.06, unit="arb"),
        ),
    ),
    defaults={
        "coupler": "coupler-q0-q1",
        "drive_length": None,
        "flux_bias": sc.Quantity(value=0.06, unit="arb"),
    },
    metadata={"category": "rabi"},
)

SYSTEM_BACKGROUND_RABI_TEMPLATE = sc.template(
    id=SYSTEM_BACKGROUND_RABI_TEMPLATE_ID,
    experiment_id="system-background-rabi",
    kind="system_background_rabi",
    sources=(
        sc.around_points(
            "drive_length",
            center=qubit_param("rabi_pulse_length"),
            default_span=sc.Quantity(value=80.0, unit="ns"),
            points=5,
            input_id="drive_length",
        ),
        SYSTEM_COUPLER_PARKING_BACKGROUND_MODULE,
        RABI_MODULE,
        READOUT_CAPTURE_MODULE,
        PROBABILITY_1_RECORD_MODULE,
        RAW_IQ_RECORD_MODULE,
        sc.record_product("probability_1"),
        sc.record_product("raw_iq"),
    ),
    label="parameter-table background Rabi",
    description=(
        "Build a Rabi scan while materializing all coupler parking flux "
        "background outputs from the accepted two-qubit gate parameter table."
    ),
    inputs=(
        sc.InputDescription(id="qubit", kind="entity"),
        sc.InputDescription(id="drive_length", kind="quantity"),
    ),
    defaults={"drive_length": None},
    metadata={"category": "rabi"},
)

READOUT_TEMPLATE = sc.template(
    id=READOUT_TEMPLATE_ID,
    experiment_id="readout-frequency",
    kind="readout_frequency",
    sources=(
        sc.around_points(
            "readout_frequency",
            center=qubit_param("readout_frequency"),
            default_span=sc.Quantity(value=100.0, unit="MHz"),
            points=5,
            input_id="readout_frequency",
        ),
        READOUT_MODULE,
        READOUT_CAPTURE_MODULE,
        RAW_IQ_RECORD_MODULE,
        READOUT_CLASSIFICATION_RECORDS_MODULE,
        sc.record_product("raw_iq"),
        sc.record_product("state0_iq"),
        sc.record_product("state1_iq"),
        sc.record_product("state0_iq_stdev"),
        sc.record_product("state1_iq_stdev"),
    ),
    label="readout frequency",
    description="Build a experiment-system readout frequency scan.",
    inputs=(
        sc.InputDescription(id="qubit", kind="entity"),
        sc.InputDescription(id="readout_frequency", kind="quantity"),
    ),
    defaults={"readout_frequency": None},
    metadata={"category": "readout"},
)

MULTIPLEXED_READOUT_TEMPLATE = sc.template(
    id=MULTIPLEXED_READOUT_TEMPLATE_ID,
    experiment_id="multiplexed-readout",
    kind="multiplexed_readout",
    sources=(
        MULTIPLEXED_READOUT_MODULE,
        MULTIPLEXED_IQ_RECORD_MODULE,
        sc.record_product("multiplexed_iq"),
    ),
    label="multiplexed readout",
    description="Build a simultaneous readout over an entity array.",
    inputs=(
        sc.InputDescription(
            id="qubits",
            kind="entity_array",
            default=("q0", "q1"),
        ),
    ),
    defaults={"qubits": sc.entity_array(("q0", "q1"))},
    metadata={"category": "readout"},
)

MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE = sc.template(
    id=MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE_ID,
    experiment_id="multiplexed-readout-calibration",
    kind="multiplexed_readout_calibration",
    sources=(
        sc.around_points(
            "readout_frequency",
            center=sc.input("center_frequency"),
            default_span=sc.Quantity(value=120.0, unit="MHz"),
            points=5,
            input_id="readout_frequency",
        ),
        MULTIPLEXED_READOUT_PULSE_MODULE,
        MULTIPLEXED_READOUT_MODULE,
        MULTIPLEXED_IQ_RECORD_MODULE,
        sc.record_product("multiplexed_iq"),
    ),
    label="multiplexed readout calibration",
    description="Build a shared readout-frequency scan returning an entity array.",
    inputs=(
        sc.InputDescription(
            id="qubits",
            kind="entity_array",
            default=("q0", "q1"),
        ),
        sc.InputDescription(id="readout_frequency", kind="quantity"),
        sc.InputDescription(
            id="center_frequency",
            kind="quantity",
            default=sc.Quantity(value=6.6, unit="GHz"),
        ),
        sc.InputDescription(
            id="readout_power",
            kind="quantity",
            default=sc.Quantity(value=-20.5, unit="dBm"),
        ),
    ),
    defaults={
        "qubits": sc.entity_array(("q0", "q1")),
        "readout_frequency": None,
        "center_frequency": sc.Quantity(value=6.6, unit="GHz"),
        "readout_power": sc.Quantity(value=-20.5, unit="dBm"),
    },
    metadata={"category": "readout"},
)

SQG_RB_TEMPLATE = sc.template(
    id=SQG_RB_TEMPLATE_ID,
    experiment_id="sqg-rb",
    kind="sqg_rb",
    sources=(
        sc.value_points(
            "clifford_count",
            (4, 8, 16),
            unit="count",
            input_id="lengths",
        ),
        SQG_RB_MODULE,
        READOUT_CAPTURE_MODULE,
        PROBABILITY_RECORDS_MODULE,
        RAW_IQ_RECORD_MODULE,
        sc.record_product("probability_0"),
        sc.record_product("probability_1"),
        sc.record_product("raw_iq"),
    ),
    label="SQG RB",
    description="Build a experiment-system single-qubit randomized benchmarking scan.",
    inputs=(
        sc.InputDescription(id="qubit", kind="entity"),
        sc.InputDescription(id="lengths", kind="point_values"),
        sc.InputDescription(id="seed", kind="seed", default=0),
    ),
    defaults={"lengths": None, "seed": 0},
    metadata={"category": "gate_based"},
)

CZ_RB_TEMPLATE = sc.template(
    id=CZ_RB_TEMPLATE_ID,
    experiment_id="cz-rb",
    kind="cz_rb",
    sources=(
        sc.value_points(
            "clifford_count",
            (2, 4, 8),
            unit="count",
            input_id="lengths",
        ),
        CZ_RB_MODULE,
        READOUT_CAPTURE_MODULE,
        PROBABILITY_RECORDS_MODULE,
        RAW_IQ_RECORD_MODULE,
        sc.record_product("probability_0"),
        sc.record_product("probability_1"),
        sc.record_product("raw_iq"),
    ),
    label="CZ RB",
    description="Build a experiment-system two-qubit CZ randomized benchmarking scan.",
    inputs=(
        sc.InputDescription(id="control_qubit", kind="entity"),
        sc.InputDescription(id="partner_qubit", kind="entity"),
        sc.InputDescription(id="coupler", kind="entity", default="coupler-q0-q1"),
        sc.InputDescription(id="lengths", kind="point_values"),
        sc.InputDescription(id="seed", kind="seed", default=0),
        sc.InputDescription(id="interleaved_gate", kind="gate_label", default="CZ"),
    ),
    defaults={
        "coupler": "coupler-q0-q1",
        "lengths": None,
        "seed": 0,
        "interleaved_gate": "CZ",
    },
    metadata={"category": "gate_based"},
)

CZ_CHEVRON_TEMPLATE = sc.template(
    id=CZ_CHEVRON_TEMPLATE_ID,
    experiment_id="cz-chevron",
    kind="cz_chevron",
    sources=(
        sc.value_points(
            "coupler_duration",
            (24, 36, 48),
            unit="ns",
            input_id="durations",
        ),
        sc.value_points(
            "coupler_amplitude",
            (0.18, 0.24, 0.30),
            unit="arb",
            input_id="amplitudes",
        ),
        CZ_CHEVRON_MODULE,
        READOUT_CAPTURE_MODULE,
        PROBABILITY_RECORDS_MODULE,
        RAW_IQ_RECORD_MODULE,
        sc.record_product("probability_0"),
        sc.record_product("probability_1"),
        sc.record_product("raw_iq"),
    ),
    label="CZ chevron",
    description="Build a two-dimensional CZ amplitude-duration calibration scan.",
    inputs=(
        sc.InputDescription(id="control_qubit", kind="entity"),
        sc.InputDescription(id="partner_qubit", kind="entity"),
        sc.InputDescription(id="coupler", kind="entity", default="coupler-q0-q1"),
        sc.InputDescription(id="durations", kind="point_values"),
        sc.InputDescription(id="amplitudes", kind="point_values"),
    ),
    defaults={
        "coupler": "coupler-q0-q1",
        "durations": None,
        "amplitudes": None,
    },
    metadata={"category": "gate_based"},
)

SPECTATOR_CZ_TEMPLATE = sc.template(
    id=SPECTATOR_CZ_TEMPLATE_ID,
    experiment_id="spectator-cz-calibration",
    kind="spectator_cz_calibration",
    sources=(
        sc.value_points(
            "coupler_duration",
            (24, 36),
            unit="ns",
            input_id="durations",
        ),
        sc.value_points(
            "coupler_amplitude",
            (0.18, 0.24),
            unit="arb",
            input_id="amplitudes",
        ),
        SPECTATOR_FLUX_BACKGROUND_MODULE,
        CZ_CHEVRON_MODULE,
        READOUT_CAPTURE_MODULE,
        PROBABILITY_RECORDS_MODULE,
        RAW_IQ_RECORD_MODULE,
        sc.record_product("probability_0"),
        sc.record_product("probability_1"),
        sc.record_product("raw_iq"),
    ),
    label="spectator-aware CZ calibration",
    description=(
        "Build a CZ calibration while maintaining explicit spectator "
        "background flux state."
    ),
    inputs=(
        sc.InputDescription(id="control_qubit", kind="entity"),
        sc.InputDescription(id="partner_qubit", kind="entity"),
        sc.InputDescription(id="coupler", kind="entity", default="coupler-q0-q1"),
        sc.InputDescription(
            id="background_couplers",
            kind="entity_array",
            default=("coupler-q2-q3",),
        ),
        sc.InputDescription(id="durations", kind="point_values"),
        sc.InputDescription(id="amplitudes", kind="point_values"),
        sc.InputDescription(
            id="spectator_flux_bias",
            kind="quantity",
            default=sc.Quantity(value=0.025, unit="arb"),
        ),
    ),
    defaults={
        "coupler": "coupler-q0-q1",
        "background_couplers": sc.entity_array(("coupler-q2-q3",)),
        "durations": None,
        "amplitudes": None,
        "spectator_flux_bias": sc.Quantity(value=0.025, unit="arb"),
    },
    metadata={"category": "gate_based"},
)

PARALLEL_GATE_SET_TEMPLATE = sc.template(
    id=PARALLEL_GATE_SET_TEMPLATE_ID,
    experiment_id="parallel-gate-set",
    kind="parallel_gate_set",
    sources=(
        sc.value_points(
            "gate_duration",
            (28, 36),
            unit="ns",
            input_id="durations",
        ),
        PARALLEL_GATE_SET_MODULE,
        MULTIPLEXED_READOUT_MODULE,
        MULTIPLEXED_IQ_RECORD_MODULE,
        sc.record_product("multiplexed_iq"),
    ),
    label="parallel gate set",
    description=(
        "Build two disjoint CZ calibrations in one logical point stream to "
        "exercise route fan-out and entity-axis records."
    ),
    inputs=(
        sc.InputDescription(id="control_qubit_a", kind="entity", default="q0"),
        sc.InputDescription(id="partner_qubit_a", kind="entity", default="q1"),
        sc.InputDescription(
            id="coupler_a",
            kind="entity",
            default="coupler-q0-q1",
        ),
        sc.InputDescription(id="control_qubit_b", kind="entity", default="q2"),
        sc.InputDescription(id="partner_qubit_b", kind="entity", default="q3"),
        sc.InputDescription(
            id="coupler_b",
            kind="entity",
            default="coupler-q2-q3",
        ),
        sc.InputDescription(
            id="qubits",
            kind="entity_array",
            default=("q0", "q1", "q2", "q3"),
        ),
        sc.InputDescription(id="durations", kind="point_values"),
    ),
    defaults={
        "control_qubit_a": "q0",
        "partner_qubit_a": "q1",
        "coupler_a": "coupler-q0-q1",
        "control_qubit_b": "q2",
        "partner_qubit_b": "q3",
        "coupler_b": "coupler-q2-q3",
        "qubits": sc.entity_array(("q0", "q1", "q2", "q3")),
        "durations": None,
    },
    metadata={"category": "gate_based"},
)

TOY_SURFACE_CODE_ROUND_TEMPLATE = sc.template(
    id=TOY_SURFACE_CODE_ROUND_TEMPLATE_ID,
    experiment_id="toy-surface-code-round",
    kind="toy_surface_code_round",
    sources=(
        TOY_SURFACE_CODE_ROUND_MODULE,
        STABILIZER_IQ_RECORD_MODULE,
        sc.record_product("stabilizer_iq"),
    ),
    label="toy surface-code round",
    description=(
        "Build a small stabilizer-round schedule with drive, coupler, and "
        "round-by-entity readout output."
    ),
    inputs=(
        sc.InputDescription(
            id="patch_qubits",
            kind="entity_array",
            default=("q0", "q1", "q2", "q3"),
        ),
        sc.InputDescription(
            id="data_qubits",
            kind="entity_array",
            default=("q0", "q1"),
        ),
        sc.InputDescription(
            id="ancilla_qubits",
            kind="entity_array",
            default=("q2", "q3"),
        ),
        sc.InputDescription(
            id="couplers",
            kind="entity_array",
            default=("coupler-q0-q1", "coupler-q2-q3"),
        ),
        sc.InputDescription(
            id="rounds",
            kind="quantity",
            default=sc.Quantity(value=3.0, unit="count"),
        ),
        sc.InputDescription(
            id="cycle_time",
            kind="quantity",
            default=sc.Quantity(value=32.0, unit="ns"),
        ),
    ),
    defaults={
        "patch_qubits": sc.entity_array(("q0", "q1", "q2", "q3")),
        "data_qubits": sc.entity_array(("q0", "q1")),
        "ancilla_qubits": sc.entity_array(("q2", "q3")),
        "couplers": sc.entity_array(("coupler-q0-q1", "coupler-q2-q3")),
        "rounds": sc.Quantity(value=3.0, unit="count"),
        "cycle_time": sc.Quantity(value=32.0, unit="ns"),
    },
    metadata={"category": "surface_code"},
)

QND_REPEATED_MEASUREMENT_TEMPLATE = sc.template(
    id=QND_REPEATED_MEASUREMENT_TEMPLATE_ID,
    experiment_id="qnd-repeated-measurement",
    kind="qnd_repeated_measurement",
    sources=(
        QND_REPEATED_MEASUREMENT_MODULE,
        QND_IQ_RECORD_MODULE,
        sc.record_product("qnd_iq"),
    ),
    label="QND repeated measurement",
    description="Build a repeated readout returning one dense round-by-shot array.",
    inputs=(
        sc.InputDescription(id="qubit", kind="entity"),
        sc.InputDescription(
            id="rounds",
            kind="quantity",
            default=sc.Quantity(value=4.0, unit="count"),
        ),
        sc.InputDescription(
            id="shots",
            kind="quantity",
            default=sc.Quantity(value=16.0, unit="count"),
        ),
    ),
    defaults={
        "rounds": sc.Quantity(value=4.0, unit="count"),
        "shots": sc.Quantity(value=16.0, unit="count"),
    },
    metadata={"category": "readout"},
)

BACKEND_BATCH_TEMPLATE = sc.template(
    id=BACKEND_BATCH_TEMPLATE_ID,
    experiment_id="backend-batch-out-of-order",
    kind="backend_batch_out_of_order",
    sources=(
        BACKEND_BATCH_MODULE,
        BACKEND_PROBABILITY_RECORD_MODULE,
        sc.record_product("backend_probabilities"),
    ),
    label="backend batch out-of-order",
    description=(
        "Build a backend-batch mock that keeps logical batch points inside one "
        "array output and records returned order in the compute payload."
    ),
    inputs=(
        sc.InputDescription(
            id="logical_points",
            kind="quantity",
            default=sc.Quantity(value=5.0, unit="count"),
        ),
        sc.InputDescription(id="seed", kind="seed", default=7),
    ),
    defaults={
        "logical_points": sc.Quantity(value=5.0, unit="count"),
        "seed": 7,
    },
    metadata={"category": "backend"},
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

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
    PARALLEL_GATE_QUBITS,
    PARALLEL_GATE_SET_MODULE,
)


def _template(
    id: str,  # noqa: A002
    *,
    kind: str,
    modules: tuple[sc.ExperimentModule | sc.ModuleInvocation, ...],
) -> sc.TemplateBuilder:
    return sc.module(f"{id}.root").use(*modules).template(id, kind=kind)


RABI_TEMPLATE = (
    _template(
        RABI_TEMPLATE_ID,
        kind="rabi",
        modules=(
            RABI_MODULE,
            READOUT_CAPTURE_MODULE,
            PROBABILITY_1_RECORD_MODULE,
            RAW_IQ_RECORD_MODULE,
        ),
    )
    .experiment_id("rabi")
    .scan(
        "drive_length",
        center=qubit_param("rabi_pulse_length"),
        span=sc.Quantity(value=80.0, unit="ns"),
        points=5,
    )
    .record_product("probability_1", "raw_iq")
    .label("Rabi")
    .description("Build a experiment-system single-qubit Rabi length scan.")
    .inputs(
        sc.InputDescription(id="qubit"),
    )
    .metadata(category="rabi")
)

SIMULTANEOUS_RABI_TEMPLATE = (
    _template(
        SIMULTANEOUS_RABI_TEMPLATE_ID,
        kind="simultaneous_rabi",
        modules=(
            SIMULTANEOUS_RABI_MODULE,
            MULTIPLEXED_READOUT_MODULE,
            MULTIPLEXED_IQ_RECORD_MODULE,
        ),
    )
    .experiment_id("simultaneous-rabi")
    .scan(
        "drive_length",
        center=sc.input("center_length"),
        span=sc.Quantity(value=60.0, unit="ns"),
        points=5,
    )
    .record_product("multiplexed_iq")
    .label("simultaneous Rabi")
    .description("Build a simultaneous multi-qubit Rabi scan with array readout.")
    .inputs(
        sc.InputDescription(
            id="qubits",
            default=("q0", "q1"),
        ),
        sc.InputDescription(
            id="center_length",
            default=sc.Quantity(value=48.0, unit="ns"),
        ),
        sc.InputDescription(
            id="drive_amplitude",
            default=sc.Quantity(value=0.28, unit="arb"),
        ),
        sc.InputDescription(
            id="drive_frequency",
            default=sc.Quantity(value=5.1, unit="GHz"),
        ),
    )
    .metadata(category="rabi")
)

FLUX_BACKGROUND_RABI_TEMPLATE = (
    _template(
        FLUX_BACKGROUND_RABI_TEMPLATE_ID,
        kind="flux_background_rabi",
        modules=(
            FLUX_BACKGROUND_MODULE,
            RABI_MODULE,
            READOUT_CAPTURE_MODULE,
            PROBABILITY_1_RECORD_MODULE,
            RAW_IQ_RECORD_MODULE,
        ),
    )
    .experiment_id("flux-background-rabi")
    .scan(
        "drive_length",
        center=qubit_param("rabi_pulse_length"),
        span=sc.Quantity(value=80.0, unit="ns"),
        points=5,
    )
    .record_product("probability_1", "raw_iq")
    .label("flux-background Rabi")
    .description("Build a Rabi scan while holding a coupler flux-bias background.")
    .inputs(
        sc.InputDescription(id="qubit"),
        sc.InputDescription(
            id="coupler",
            default="coupler-q0-q1",
        ),
        sc.InputDescription(
            id="flux_bias",
            default=sc.Quantity(value=0.06, unit="arb"),
        ),
    )
    .metadata(category="rabi")
)

SYSTEM_BACKGROUND_RABI_TEMPLATE = (
    _template(
        SYSTEM_BACKGROUND_RABI_TEMPLATE_ID,
        kind="system_background_rabi",
        modules=(
            SYSTEM_COUPLER_PARKING_BACKGROUND_MODULE,
            RABI_MODULE,
            READOUT_CAPTURE_MODULE,
            PROBABILITY_1_RECORD_MODULE,
            RAW_IQ_RECORD_MODULE,
        ),
    )
    .experiment_id("system-background-rabi")
    .scan(
        "drive_length",
        center=qubit_param("rabi_pulse_length"),
        span=sc.Quantity(value=80.0, unit="ns"),
        points=5,
    )
    .record_product("probability_1", "raw_iq")
    .label("parameter-table background Rabi")
    .description(
        "Build a Rabi scan while materializing all coupler parking flux "
        "background outputs from the accepted two-qubit gate parameter table."
    )
    .inputs(
        sc.InputDescription(id="qubit"),
    )
    .metadata(category="rabi")
)

READOUT_TEMPLATE = (
    _template(
        READOUT_TEMPLATE_ID,
        kind="readout_frequency",
        modules=(
            READOUT_MODULE,
            READOUT_CAPTURE_MODULE,
            RAW_IQ_RECORD_MODULE,
            READOUT_CLASSIFICATION_RECORDS_MODULE,
        ),
    )
    .experiment_id("readout-frequency")
    .scan(
        "readout_frequency",
        center=qubit_param("readout_frequency"),
        span=sc.Quantity(value=100.0, unit="MHz"),
        points=5,
    )
    .record_product("raw_iq", "state0_iq", "state1_iq")
    .record_product("state0_iq_stdev", "state1_iq_stdev")
    .label("readout frequency")
    .description("Build a experiment-system readout frequency scan.")
    .inputs(
        sc.InputDescription(id="qubit"),
    )
    .metadata(category="readout")
)

MULTIPLEXED_READOUT_TEMPLATE = (
    _template(
        MULTIPLEXED_READOUT_TEMPLATE_ID,
        kind="multiplexed_readout",
        modules=(
            MULTIPLEXED_READOUT_MODULE,
            MULTIPLEXED_IQ_RECORD_MODULE,
        ),
    )
    .experiment_id("multiplexed-readout")
    .record_product("multiplexed_iq")
    .label("multiplexed readout")
    .description("Build a simultaneous readout over an entity series.")
    .inputs(
        sc.InputDescription(
            id="qubits",
            default=("q0", "q1"),
        ),
    )
    .metadata(category="readout")
)

MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE = (
    _template(
        MULTIPLEXED_READOUT_CALIBRATION_TEMPLATE_ID,
        kind="multiplexed_readout_calibration",
        modules=(
            MULTIPLEXED_READOUT_PULSE_MODULE,
            MULTIPLEXED_READOUT_MODULE,
            MULTIPLEXED_IQ_RECORD_MODULE,
        ),
    )
    .experiment_id("multiplexed-readout-calibration")
    .scan(
        "readout_frequency",
        center=sc.input("center_frequency"),
        span=sc.Quantity(value=120.0, unit="MHz"),
        points=5,
    )
    .record_product("multiplexed_iq")
    .label("multiplexed readout calibration")
    .description("Build a shared readout-frequency scan returning an entity series.")
    .inputs(
        sc.InputDescription(
            id="qubits",
            default=("q0", "q1"),
        ),
        sc.InputDescription(
            id="center_frequency",
            default=sc.Quantity(value=6.6, unit="GHz"),
        ),
        sc.InputDescription(
            id="readout_power",
            default=sc.Quantity(value=-20.5, unit="dBm"),
        ),
    )
    .metadata(category="readout")
)

SQG_RB_TEMPLATE = (
    _template(
        SQG_RB_TEMPLATE_ID,
        kind="sqg_rb",
        modules=(
            SQG_RB_MODULE,
            READOUT_CAPTURE_MODULE,
            PROBABILITY_RECORDS_MODULE,
            RAW_IQ_RECORD_MODULE,
        ),
    )
    .experiment_id("sqg-rb")
    .scan("clifford_count", (4, 8, 16))
    .record_product("probability_0", "probability_1", "raw_iq")
    .label("SQG RB")
    .description("Build a experiment-system single-qubit randomized benchmarking scan.")
    .inputs(
        sc.InputDescription(id="qubit"),
        sc.InputDescription(id="seed", default=0),
    )
    .metadata(category="gate_based")
)

CZ_RB_TEMPLATE = (
    _template(
        CZ_RB_TEMPLATE_ID,
        kind="cz_rb",
        modules=(
            CZ_RB_MODULE,
            READOUT_CAPTURE_MODULE,
            PROBABILITY_RECORDS_MODULE,
            RAW_IQ_RECORD_MODULE,
        ),
    )
    .experiment_id("cz-rb")
    .scan("clifford_count", (2, 4, 8))
    .record_product("probability_0", "probability_1", "raw_iq")
    .label("CZ RB")
    .description("Build a experiment-system two-qubit CZ randomized benchmarking scan.")
    .inputs(
        sc.InputDescription(id="control_qubit"),
        sc.InputDescription(id="partner_qubit"),
        sc.InputDescription(id="coupler", default="coupler-q0-q1"),
        sc.InputDescription(id="seed", default=0),
        sc.InputDescription(id="interleaved_gate", default="CZ"),
    )
    .metadata(category="gate_based")
)

CZ_CHEVRON_TEMPLATE = (
    _template(
        CZ_CHEVRON_TEMPLATE_ID,
        kind="cz_chevron",
        modules=(
            CZ_CHEVRON_MODULE,
            READOUT_CAPTURE_MODULE,
            PROBABILITY_RECORDS_MODULE,
            RAW_IQ_RECORD_MODULE,
        ),
    )
    .experiment_id("cz-chevron")
    .scan("coupler_duration", (24, 36, 48), unit="ns")
    .scan(
        "coupler_amplitude",
        (0.18, 0.24, 0.30),
        unit="arb",
    )
    .record_product("probability_0", "probability_1", "raw_iq")
    .label("CZ chevron")
    .description("Build a two-dimensional CZ amplitude-duration calibration scan.")
    .inputs(
        sc.InputDescription(id="control_qubit"),
        sc.InputDescription(id="partner_qubit"),
        sc.InputDescription(id="coupler", default="coupler-q0-q1"),
    )
    .metadata(category="gate_based")
)

SPECTATOR_CZ_TEMPLATE = (
    _template(
        SPECTATOR_CZ_TEMPLATE_ID,
        kind="spectator_cz_calibration",
        modules=(
            SPECTATOR_FLUX_BACKGROUND_MODULE,
            CZ_CHEVRON_MODULE,
            READOUT_CAPTURE_MODULE,
            PROBABILITY_RECORDS_MODULE,
            RAW_IQ_RECORD_MODULE,
        ),
    )
    .experiment_id("spectator-cz-calibration")
    .scan("coupler_duration", (24, 36), unit="ns")
    .scan("coupler_amplitude", (0.18, 0.24), unit="arb")
    .record_product("probability_0", "probability_1", "raw_iq")
    .label("spectator-aware CZ calibration")
    .description(
        "Build a CZ calibration while maintaining explicit spectator "
        "background flux state."
    )
    .inputs(
        sc.InputDescription(id="control_qubit"),
        sc.InputDescription(id="partner_qubit"),
        sc.InputDescription(id="coupler", default="coupler-q0-q1"),
        sc.InputDescription(
            id="background_couplers",
            default=("coupler-q2-q3",),
        ),
        sc.InputDescription(
            id="spectator_flux_bias",
            default=sc.Quantity(value=0.025, unit="arb"),
        ),
    )
    .metadata(category="gate_based")
)

PARALLEL_GATE_SET_TEMPLATE = (
    _template(
        PARALLEL_GATE_SET_TEMPLATE_ID,
        kind="parallel_gate_set",
        modules=(
            PARALLEL_GATE_SET_MODULE,
            MULTIPLEXED_READOUT_MODULE(qubits=PARALLEL_GATE_QUBITS),
            MULTIPLEXED_IQ_RECORD_MODULE(qubits=PARALLEL_GATE_QUBITS),
        ),
    )
    .experiment_id("parallel-gate-set")
    .scan("gate_duration", (28, 36), unit="ns")
    .record_product("multiplexed_iq")
    .label("parallel gate set")
    .description(
        "Build a table-defined set of disjoint CZ calibrations in one logical "
        "point stream to "
        "exercise route fan-out and entity-axis records."
    )
    .inputs(
        sc.InputDescription(
            id="gates",
            default=(
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
            ),
        ),
    )
    .metadata(category="gate_based")
)

TOY_SURFACE_CODE_ROUND_TEMPLATE = (
    _template(
        TOY_SURFACE_CODE_ROUND_TEMPLATE_ID,
        kind="toy_surface_code_round",
        modules=(
            TOY_SURFACE_CODE_ROUND_MODULE,
            STABILIZER_IQ_RECORD_MODULE,
        ),
    )
    .experiment_id("toy-surface-code-round")
    .record_product("stabilizer_iq")
    .label("toy surface-code round")
    .description(
        "Build a small stabilizer-round schedule with drive, coupler, and "
        "round-by-entity readout output."
    )
    .inputs(
        sc.InputDescription(
            id="patch_qubits",
            default=("q0", "q1", "q2", "q3"),
        ),
        sc.InputDescription(
            id="data_qubits",
            default=("q0", "q1"),
        ),
        sc.InputDescription(
            id="ancilla_qubits",
            default=("q2", "q3"),
        ),
        sc.InputDescription(
            id="couplers",
            default=("coupler-q0-q1", "coupler-q2-q3"),
        ),
        sc.InputDescription(
            id="rounds",
            default=3,
        ),
        sc.InputDescription(
            id="cycle_time",
            default=sc.Quantity(value=32.0, unit="ns"),
        ),
    )
    .metadata(category="surface_code")
)

QND_REPEATED_MEASUREMENT_TEMPLATE = (
    _template(
        QND_REPEATED_MEASUREMENT_TEMPLATE_ID,
        kind="qnd_repeated_measurement",
        modules=(
            QND_REPEATED_MEASUREMENT_MODULE,
            QND_IQ_RECORD_MODULE,
        ),
    )
    .experiment_id("qnd-repeated-measurement")
    .record_product("qnd_iq")
    .label("QND repeated measurement")
    .description("Build a repeated readout returning one dense round-by-shot array.")
    .inputs(
        sc.InputDescription(id="qubit"),
        sc.InputDescription(
            id="rounds",
            default=4,
        ),
        sc.InputDescription(
            id="shots",
            default=16,
        ),
    )
    .metadata(category="readout")
)

BACKEND_BATCH_TEMPLATE = (
    _template(
        BACKEND_BATCH_TEMPLATE_ID,
        kind="backend_batch_out_of_order",
        modules=(
            BACKEND_BATCH_MODULE,
            BACKEND_PROBABILITY_RECORD_MODULE,
        ),
    )
    .experiment_id("backend-batch-out-of-order")
    .record_product("backend_probabilities")
    .label("backend batch out-of-order")
    .description(
        "Build a backend-batch mock that keeps logical batch points inside one "
        "array output and records returned order in the compute payload."
    )
    .inputs(
        sc.InputDescription(
            id="logical_points",
            default=5,
        ),
        sc.InputDescription(id="seed", default=7),
    )
    .metadata(category="backend")
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

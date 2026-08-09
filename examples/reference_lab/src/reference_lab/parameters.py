"""Typed parameter schema and initial values for the reference laboratory."""

from __future__ import annotations

import scopecat as sc
from scopecat.records.parameter import (
    ParameterSnapshot,
    TableParameterValue,
)

QUBIT = sc.parameter_field(
    "qubit",
    sc.EntityType(entity_kind="logical_qubit"),
)
DRAG_BETA = sc.parameter_field("drag_beta", sc.QuantityType(unit="ns"))
QUARTER_TURN_DURATION = sc.parameter_field(
    "quarter_turn_duration",
    sc.QuantityType(unit="ns"),
)
QUARTER_TURN_AMPLITUDE = sc.parameter_field(
    "quarter_turn_amplitude",
    sc.QuantityType(unit="arb"),
)
QUARTER_TURN_SIGMA = sc.parameter_field(
    "quarter_turn_sigma",
    sc.QuantityType(unit="ns"),
)
DRIVE_CARRIER_FREQUENCY = sc.parameter_field(
    "drive_carrier_frequency",
    sc.QuantityType(unit="Hz"),
)
QUBITS = sc.parameter_schema(
    "qubits",
    fields=(
        QUBIT,
        DRAG_BETA,
        QUARTER_TURN_DURATION,
        QUARTER_TURN_AMPLITUDE,
        QUARTER_TURN_SIGMA,
        DRIVE_CARRIER_FREQUENCY,
    ),
    primary_key=(QUBIT,),
    description="Reviewed per-qubit drive carrier and DRAG calibration values.",
)
Q0 = QUBITS.row(
    QUBIT.key("q0"),
)
Q1 = QUBITS.row(
    QUBIT.key("q1"),
)
Q2 = QUBITS.row(QUBIT.key("q2"))
Q3 = QUBITS.row(QUBIT.key("q3"))
Q0_DRAG_BETA = Q0[DRAG_BETA]

IQ_CHAIN = sc.parameter_field("chain", sc.StringType())
MIXER_II = sc.parameter_field("mixer_ii", sc.FloatType())
MIXER_IQ = sc.parameter_field("mixer_iq", sc.FloatType())
MIXER_QI = sc.parameter_field("mixer_qi", sc.FloatType())
MIXER_QQ = sc.parameter_field("mixer_qq", sc.FloatType())
MIXER_I_OFFSET = sc.parameter_field("mixer_i_offset", sc.QuantityType(unit="V"))
MIXER_Q_OFFSET = sc.parameter_field("mixer_q_offset", sc.QuantityType(unit="V"))
IQ_CHAINS = sc.parameter_schema(
    "iq_chains",
    fields=(
        IQ_CHAIN,
        MIXER_II,
        MIXER_IQ,
        MIXER_QI,
        MIXER_QQ,
        MIXER_I_OFFSET,
        MIXER_Q_OFFSET,
    ),
    primary_key=(IQ_CHAIN,),
    description=(
        "Reviewed physical IQ-chain calibration. Logical signal membership and "
        "physical DAC routes live in infrastructure configuration."
    ),
)


DRIVE_Q0_IQ_CHAIN = IQ_CHAINS.row(IQ_CHAIN.key("drive-q0"))
DRIVE_Q1_IQ_CHAIN = IQ_CHAINS.row(IQ_CHAIN.key("drive-q1"))
DRIVE_Q2_IQ_CHAIN = IQ_CHAINS.row(IQ_CHAIN.key("drive-q2"))
DRIVE_Q3_IQ_CHAIN = IQ_CHAINS.row(IQ_CHAIN.key("drive-q3"))
READOUT_IQ_CHAIN = IQ_CHAINS.row(IQ_CHAIN.key("readout"))
IQ_CHAIN_ROWS = (
    DRIVE_Q0_IQ_CHAIN,
    DRIVE_Q1_IQ_CHAIN,
    DRIVE_Q2_IQ_CHAIN,
    DRIVE_Q3_IQ_CHAIN,
    READOUT_IQ_CHAIN,
)

AWG_OUTPUT_SLOT = sc.parameter_field("slot", sc.StringType())
AWG_OUTPUT_OFFSET = sc.parameter_field("offset", sc.QuantityType(unit="V"))
AWG_OUTPUT_BASELINES = sc.parameter_schema(
    "awg_output_baselines",
    fields=(AWG_OUTPUT_SLOT, AWG_OUTPUT_OFFSET),
    primary_key=(AWG_OUTPUT_SLOT,),
    description=("Reviewed state for lab policy slots that are not logical IQ chains."),
)
DRIVE_AWG_OFFSET_GUARD_SLOT_ID = "drive-awg.offset-guard"
DRIVE_AWG_OFFSET_GUARD_BASELINE = AWG_OUTPUT_BASELINES.row(
    AWG_OUTPUT_SLOT.key(DRIVE_AWG_OFFSET_GUARD_SLOT_ID)
)

LO_GROUP = sc.parameter_field("group", sc.StringType())
LO_FREQUENCY = sc.parameter_field("frequency", sc.QuantityType(unit="Hz"))
LO_POWER = sc.parameter_field("power", sc.QuantityType(unit="dBm"))
LO_GROUPS = sc.parameter_schema(
    "lo_groups",
    fields=(LO_GROUP, LO_FREQUENCY, LO_POWER),
    primary_key=(LO_GROUP,),
    description="Reviewed setpoints for statically wired LO distribution groups.",
)
DRIVE_LO_A = LO_GROUPS.row(LO_GROUP.key("drive-a"))
DRIVE_LO_B = LO_GROUPS.row(LO_GROUP.key("drive-b"))
READOUT_LO = LO_GROUPS.row(LO_GROUP.key("readout"))

RESONATOR = sc.parameter_field(
    "resonator",
    sc.EntityType(entity_kind="logical_qubit"),
)
RESONANCE_FREQUENCY = sc.parameter_field(
    "resonance_frequency",
    sc.QuantityType(unit="Hz"),
)
RESONATOR_LINEWIDTH = sc.parameter_field(
    "linewidth",
    sc.QuantityType(unit="Hz"),
)
FLUX_SWEET_SPOT = sc.parameter_field(
    "flux_sweet_spot",
    sc.QuantityType(unit="V"),
)
READOUT_RESONATORS = sc.parameter_schema(
    "readout_resonators",
    fields=(
        RESONATOR,
        RESONANCE_FREQUENCY,
        RESONATOR_LINEWIDTH,
        FLUX_SWEET_SPOT,
    ),
    primary_key=(RESONATOR,),
    description="Reviewed readout resonator calibration values.",
)
Q0_READOUT = READOUT_RESONATORS.row(RESONATOR.key("q0"))
Q1_READOUT = READOUT_RESONATORS.row(RESONATOR.key("q1"))
Q2_READOUT = READOUT_RESONATORS.row(RESONATOR.key("q2"))
Q3_READOUT = READOUT_RESONATORS.row(RESONATOR.key("q3"))

CALIBRATION_QUBIT = sc.parameter_field(
    "qubit",
    sc.EntityType(entity_kind="logical_qubit"),
)
CHANNEL_DELAY = sc.parameter_field("channel_delay", sc.QuantityType(unit="ns"))
FLUX_GAIN = sc.parameter_field("flux_gain", sc.FloatType())
FLUX_POLARITY = sc.parameter_field("flux_polarity", sc.IntType())
FLUX_OFFSET = sc.parameter_field("flux_offset", sc.QuantityType(unit="V"))
CHANNEL_CALIBRATIONS = sc.parameter_schema(
    "channel_calibrations",
    fields=(
        CALIBRATION_QUBIT,
        CHANNEL_DELAY,
        FLUX_GAIN,
        FLUX_POLARITY,
        FLUX_OFFSET,
    ),
    primary_key=(CALIBRATION_QUBIT,),
    description="Reviewed per-qubit line calibration; physical routes live in config.",
)
Q0_CHANNEL_CALIBRATION = CHANNEL_CALIBRATIONS.row(CALIBRATION_QUBIT.key("q0"))
Q1_CHANNEL_CALIBRATION = CHANNEL_CALIBRATIONS.row(CALIBRATION_QUBIT.key("q1"))
Q2_CHANNEL_CALIBRATION = CHANNEL_CALIBRATIONS.row(CALIBRATION_QUBIT.key("q2"))
Q3_CHANNEL_CALIBRATION = CHANNEL_CALIBRATIONS.row(CALIBRATION_QUBIT.key("q3"))

BIAS_PROFILE = sc.parameter_field("profile", sc.StringType())
BIAS_QUBIT = sc.parameter_field(
    "qubit",
    sc.EntityType(entity_kind="logical_qubit"),
)
LOGICAL_BIAS = sc.parameter_field("logical_bias", sc.QuantityType(unit="V"))
BIAS_PROFILES = sc.parameter_schema(
    "bias_profiles",
    fields=(BIAS_PROFILE, BIAS_QUBIT, LOGICAL_BIAS),
    primary_key=(BIAS_PROFILE, BIAS_QUBIT),
    description=(
        "Named logical operating planes; channel gain, polarity, and offset are "
        "applied separately."
    ),
)


def _bias_profile_row(profile: str, qubit: str) -> sc.ParameterRow:
    return BIAS_PROFILES.row(BIAS_PROFILE.key(profile), BIAS_QUBIT.key(qubit))


PARKED_BIAS_ROWS = tuple(_bias_profile_row("parked", f"q{index}") for index in range(4))
OPERATE_BIAS_ROWS = tuple(
    _bias_profile_row("operate", f"q{index}") for index in range(4)
)

REFERENCE_PARAMETER_CATALOG = sc.parameter_catalog(
    "reference-lab-parameter-catalog",
    QUBITS,
    IQ_CHAINS,
    AWG_OUTPUT_BASELINES,
    LO_GROUPS,
    READOUT_RESONATORS,
    CHANNEL_CALIBRATIONS,
    BIAS_PROFILES,
)


def reference_lab_parameter_snapshot() -> ParameterSnapshot:
    """Build the initial scalar and calibration tables reviewed in source."""

    return ParameterSnapshot(
        id="reference-lab-parameter-snapshot",
        values=(
            TableParameterValue(
                id=QUBITS.id,
                rows=(
                    Q0.values(
                        DRAG_BETA.value(0.5),
                        QUARTER_TURN_DURATION.value(16.0),
                        QUARTER_TURN_AMPLITUDE.value(0.2),
                        QUARTER_TURN_SIGMA.value(4.0),
                        DRIVE_CARRIER_FREQUENCY.value(4.8e9),
                    ),
                    Q1.values(
                        DRAG_BETA.value(0.45),
                        QUARTER_TURN_DURATION.value(18.0),
                        QUARTER_TURN_AMPLITUDE.value(0.18),
                        QUARTER_TURN_SIGMA.value(4.5),
                        DRIVE_CARRIER_FREQUENCY.value(4.9e9),
                    ),
                    Q2.values(
                        DRAG_BETA.value(0.4),
                        QUARTER_TURN_DURATION.value(20.0),
                        QUARTER_TURN_AMPLITUDE.value(0.17),
                        QUARTER_TURN_SIGMA.value(5.0),
                        DRIVE_CARRIER_FREQUENCY.value(5.0e9),
                    ),
                    Q3.values(
                        DRAG_BETA.value(0.35),
                        QUARTER_TURN_DURATION.value(22.0),
                        QUARTER_TURN_AMPLITUDE.value(0.16),
                        QUARTER_TURN_SIGMA.value(5.5),
                        DRIVE_CARRIER_FREQUENCY.value(5.1e9),
                    ),
                ),
            ),
            TableParameterValue(
                id=READOUT_RESONATORS.id,
                rows=(
                    Q0_READOUT.values(
                        RESONANCE_FREQUENCY.value(5.0e9),
                        RESONATOR_LINEWIDTH.value(2.0e6),
                        FLUX_SWEET_SPOT.value(0.0),
                    ),
                    Q1_READOUT.values(
                        RESONANCE_FREQUENCY.value(5.2e9),
                        RESONATOR_LINEWIDTH.value(2.2e6),
                        FLUX_SWEET_SPOT.value(0.02),
                    ),
                    Q2_READOUT.values(
                        RESONANCE_FREQUENCY.value(5.4e9),
                        RESONATOR_LINEWIDTH.value(2.4e6),
                        FLUX_SWEET_SPOT.value(-0.01),
                    ),
                    Q3_READOUT.values(
                        RESONANCE_FREQUENCY.value(5.6e9),
                        RESONATOR_LINEWIDTH.value(2.6e6),
                        FLUX_SWEET_SPOT.value(0.03),
                    ),
                ),
            ),
            TableParameterValue(
                id=IQ_CHAINS.id,
                rows=tuple(
                    row.values(
                        MIXER_II.value(1.0),
                        MIXER_IQ.value(0.0),
                        MIXER_QI.value(0.0),
                        MIXER_QQ.value(1.0),
                        MIXER_I_OFFSET.value(0.0),
                        MIXER_Q_OFFSET.value(0.0),
                    )
                    for row in IQ_CHAIN_ROWS
                ),
            ),
            TableParameterValue(
                id=AWG_OUTPUT_BASELINES.id,
                rows=(
                    DRIVE_AWG_OFFSET_GUARD_BASELINE.values(
                        AWG_OUTPUT_OFFSET.value(0.007),
                    ),
                ),
            ),
            TableParameterValue(
                id=LO_GROUPS.id,
                rows=(
                    DRIVE_LO_A.values(
                        LO_FREQUENCY.value(4.85e9),
                        LO_POWER.value(-10.0),
                    ),
                    DRIVE_LO_B.values(
                        LO_FREQUENCY.value(5.05e9),
                        LO_POWER.value(-10.0),
                    ),
                    READOUT_LO.values(
                        LO_FREQUENCY.value(5.3e9),
                        LO_POWER.value(-5.0),
                    ),
                ),
            ),
            TableParameterValue(
                id=CHANNEL_CALIBRATIONS.id,
                rows=(
                    Q0_CHANNEL_CALIBRATION.values(
                        CHANNEL_DELAY.value(0.0),
                        FLUX_GAIN.value(0.98),
                        FLUX_POLARITY.value(1),
                        FLUX_OFFSET.value(0.0),
                    ),
                    Q1_CHANNEL_CALIBRATION.values(
                        CHANNEL_DELAY.value(1.5),
                        FLUX_GAIN.value(1.02),
                        FLUX_POLARITY.value(-1),
                        FLUX_OFFSET.value(0.002),
                    ),
                    Q2_CHANNEL_CALIBRATION.values(
                        CHANNEL_DELAY.value(-0.5),
                        FLUX_GAIN.value(1.01),
                        FLUX_POLARITY.value(1),
                        FLUX_OFFSET.value(-0.001),
                    ),
                    Q3_CHANNEL_CALIBRATION.values(
                        CHANNEL_DELAY.value(0.75),
                        FLUX_GAIN.value(0.99),
                        FLUX_POLARITY.value(-1),
                        FLUX_OFFSET.value(0.003),
                    ),
                ),
            ),
            TableParameterValue(
                id=BIAS_PROFILES.id,
                rows=tuple(
                    row.values(LOGICAL_BIAS.value(value))
                    for row, value in zip(
                        (*PARKED_BIAS_ROWS, *OPERATE_BIAS_ROWS),
                        (0.0, 0.0, 0.0, 0.0, -0.08, -0.02, 0.04, 0.10),
                        strict=True,
                    )
                ),
            ),
        ),
    )


__all__ = [
    "AWG_OUTPUT_BASELINES",
    "AWG_OUTPUT_OFFSET",
    "AWG_OUTPUT_SLOT",
    "BIAS_PROFILE",
    "BIAS_PROFILES",
    "BIAS_QUBIT",
    "CALIBRATION_QUBIT",
    "CHANNEL_CALIBRATIONS",
    "CHANNEL_DELAY",
    "DRAG_BETA",
    "DRIVE_AWG_OFFSET_GUARD_BASELINE",
    "DRIVE_AWG_OFFSET_GUARD_SLOT_ID",
    "DRIVE_CARRIER_FREQUENCY",
    "DRIVE_LO_A",
    "DRIVE_LO_B",
    "DRIVE_Q0_IQ_CHAIN",
    "DRIVE_Q1_IQ_CHAIN",
    "DRIVE_Q2_IQ_CHAIN",
    "DRIVE_Q3_IQ_CHAIN",
    "FLUX_GAIN",
    "FLUX_OFFSET",
    "FLUX_POLARITY",
    "FLUX_SWEET_SPOT",
    "IQ_CHAIN",
    "IQ_CHAINS",
    "IQ_CHAIN_ROWS",
    "LOGICAL_BIAS",
    "LO_FREQUENCY",
    "LO_GROUP",
    "LO_GROUPS",
    "LO_POWER",
    "MIXER_II",
    "MIXER_IQ",
    "MIXER_I_OFFSET",
    "MIXER_QI",
    "MIXER_QQ",
    "MIXER_Q_OFFSET",
    "OPERATE_BIAS_ROWS",
    "PARKED_BIAS_ROWS",
    "Q0",
    "Q0_CHANNEL_CALIBRATION",
    "Q0_DRAG_BETA",
    "Q0_READOUT",
    "Q1",
    "Q1_CHANNEL_CALIBRATION",
    "Q1_READOUT",
    "Q2",
    "Q2_CHANNEL_CALIBRATION",
    "Q2_READOUT",
    "Q3",
    "Q3_CHANNEL_CALIBRATION",
    "Q3_READOUT",
    "QUARTER_TURN_AMPLITUDE",
    "QUARTER_TURN_DURATION",
    "QUARTER_TURN_SIGMA",
    "QUBIT",
    "QUBITS",
    "READOUT_IQ_CHAIN",
    "READOUT_LO",
    "READOUT_RESONATORS",
    "REFERENCE_PARAMETER_CATALOG",
    "RESONANCE_FREQUENCY",
    "RESONATOR",
    "RESONATOR_LINEWIDTH",
    "reference_lab_parameter_snapshot",
]

from __future__ import annotations

from typing import assert_type

from scopecat.kernel.quantity import Quantity
from scopecat.sdk.instruments import DriverStatePatch

from scopecat_instruments.driver_states import (
    DCSourceDriverPatch,
    RFOutputDriverPatch,
    decode_dc_source_patch,
    decode_rf_output_patch,
    encode_dc_source_voltage_state,
    encode_driver_state,
    encode_rf_output_state,
    encode_temperature_readout_observation,
)
from scopecat_instruments.interface_declarations import (
    DCSourceState,
    DCSourceVoltageState,
    RFOutputState,
    TemperatureReadoutObservation,
)
from scopecat_instruments.members import (
    DC_SOURCE_CURRENT_PROTECTION,
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE_LEVEL,
    DC_SOURCE_VOLTAGE_PROTECTION,
    DC_SOURCE_VOLTAGE_RANGE,
    NETWORK_SWEEP_POINTS,
    RF_OUTPUT_ENABLED,
    RF_OUTPUT_FREQUENCY,
    RF_OUTPUT_POWER,
    RF_OUTPUT_REFERENCE_SOURCE,
    TEMPERATURE_READOUT_AUTOSCAN_ENABLED,
    TEMPERATURE_READOUT_SCAN_CHANNEL,
)


def test_driver_patch_decoder_preserves_presence_and_ignores_other_interfaces() -> None:
    patch = decode_rf_output_patch(
        DriverStatePatch(
            values={
                RF_OUTPUT_ENABLED: False,
                NETWORK_SWEEP_POINTS: 0,
            }
        )
    )

    assert_type(patch, RFOutputDriverPatch)
    assert "output_enabled" in patch
    assert_type(patch["output_enabled"], bool)
    assert patch == {"output_enabled": False}
    assert "frequency" not in patch


def test_exact_rf_state_encoder_uses_declared_member_refs() -> None:
    state = RFOutputState(
        frequency=Quantity(5.0e9, "Hz"),
        power=Quantity(-30.0, "dBm"),
        output_enabled=False,
        reference_source="internal",
    )

    assert encode_rf_output_state(state) == {
        RF_OUTPUT_FREQUENCY: Quantity(5.0e9, "Hz"),
        RF_OUTPUT_POWER: Quantity(-30.0, "dBm"),
        RF_OUTPUT_ENABLED: False,
        RF_OUTPUT_REFERENCE_SOURCE: "internal",
    }


def test_exact_temperature_observation_encoder_uses_declared_member_refs() -> None:
    observation = TemperatureReadoutObservation(
        scan_channel=5,
        autoscan_enabled=False,
    )

    assert encode_temperature_readout_observation(observation) == {
        TEMPERATURE_READOUT_SCAN_CHANNEL: 5,
        TEMPERATURE_READOUT_AUTOSCAN_ENABLED: False,
    }


def test_discriminated_case_encoder_uses_one_complete_canonical_state() -> None:
    patch = decode_dc_source_patch(
        DriverStatePatch(
            values={
                DC_SOURCE_MODE: "voltage",
                DC_SOURCE_VOLTAGE_RANGE: Quantity(1.0, "V"),
            }
        )
    )
    voltage = DCSourceVoltageState(
        voltage_protection=Quantity(10.0, "V"),
        current_protection=Quantity(0.01, "A"),
        output_enabled=False,
        range=Quantity(1.0, "V"),
        level=Quantity(0.25, "V"),
    )
    canonical: DCSourceState = voltage
    assert canonical is voltage

    assert_type(patch, DCSourceDriverPatch)
    assert patch == {
        "source_mode": "voltage",
        "voltage_range": Quantity(1.0, "V"),
    }
    state = encode_driver_state(
        encode_dc_source_voltage_state(voltage),
        metadata={"source": "test"},
    )
    assert state.values == {
        DC_SOURCE_MODE: "voltage",
        DC_SOURCE_VOLTAGE_PROTECTION: Quantity(10.0, "V"),
        DC_SOURCE_CURRENT_PROTECTION: Quantity(0.01, "A"),
        DC_SOURCE_OUTPUT_ENABLED: False,
        DC_SOURCE_VOLTAGE_RANGE: Quantity(1.0, "V"),
        DC_SOURCE_VOLTAGE_LEVEL: Quantity(0.25, "V"),
    }
    assert state.metadata == {"source": "test"}

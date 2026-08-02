"""Typed identities for the first-party instrument interfaces."""

from __future__ import annotations

from scopecat.sdk.instruments.declarations import (
    declared_acquisition_ref,
    declared_discriminator_ref,
    declared_interface_ref,
    declared_property_ref,
    declared_result_ref,
)

from scopecat_instruments.interface_declarations import (
    DCMonitorInterface,
    DCMonitorState,
    DCSourceCurrent,
    DCSourceInterface,
    DCSourceState,
    DCSourceVoltage,
    NetworkSweepInterface,
    NetworkSweepState,
    RFOutputInterface,
    RFOutputState,
    TemperatureReadoutInterface,
    TemperatureReadoutObservation,
)

RF_OUTPUT = declared_interface_ref(RFOutputInterface)
RF_OUTPUT_FREQUENCY = declared_property_ref(RFOutputState, "frequency")
RF_OUTPUT_POWER = declared_property_ref(RFOutputState, "power")
RF_OUTPUT_ENABLED = declared_property_ref(RFOutputState, "output_enabled")
RF_OUTPUT_REFERENCE_SOURCE = declared_property_ref(
    RFOutputState,
    "reference_source",
)

DC_SOURCE = declared_interface_ref(DCSourceInterface)
DC_SOURCE_MODE = declared_discriminator_ref(DCSourceInterface)
DC_SOURCE_VOLTAGE_RANGE = declared_property_ref(DCSourceVoltage, "range")
DC_SOURCE_CURRENT_RANGE = declared_property_ref(DCSourceCurrent, "range")
DC_SOURCE_VOLTAGE_LEVEL = declared_property_ref(DCSourceVoltage, "level")
DC_SOURCE_CURRENT_LEVEL = declared_property_ref(DCSourceCurrent, "level")
DC_SOURCE_VOLTAGE_PROTECTION = declared_property_ref(
    DCSourceState,
    "voltage_protection",
)
DC_SOURCE_CURRENT_PROTECTION = declared_property_ref(
    DCSourceState,
    "current_protection",
)
DC_SOURCE_OUTPUT_ENABLED = declared_property_ref(DCSourceState, "output_enabled")

DC_MONITOR = declared_interface_ref(DCMonitorInterface)
DC_MONITOR_MEASUREMENT_ENABLED = declared_property_ref(
    DCMonitorState,
    "measurement_enabled",
)
DC_MONITOR_INTEGRATION_CYCLES = declared_property_ref(
    DCMonitorState,
    "integration_cycles",
)
DC_MONITOR_MEASUREMENT_DELAY = declared_property_ref(
    DCMonitorState,
    "measurement_delay",
)
DC_MONITOR_ACQUISITION = declared_acquisition_ref(DCMonitorInterface, "monitor")
DC_MONITOR_CURRENT_RESULT = declared_result_ref(
    DCMonitorInterface,
    "monitor",
    "current",
)
DC_MONITOR_VOLTAGE_RESULT = declared_result_ref(
    DCMonitorInterface,
    "monitor",
    "voltage",
)

TEMPERATURE_READOUT = declared_interface_ref(TemperatureReadoutInterface)
TEMPERATURE_READOUT_SCAN_CHANNEL = declared_property_ref(
    TemperatureReadoutObservation,
    "scan_channel",
)
TEMPERATURE_READOUT_AUTOSCAN_ENABLED = declared_property_ref(
    TemperatureReadoutObservation,
    "autoscan_enabled",
)
TEMPERATURE_READOUT_SAMPLE = declared_acquisition_ref(
    TemperatureReadoutInterface,
    "sample",
)
TEMPERATURE_READOUT_TEMPERATURE_RESULT = declared_result_ref(
    TemperatureReadoutInterface,
    "sample",
    "temperature",
)
TEMPERATURE_READOUT_RESISTANCE_RESULT = declared_result_ref(
    TemperatureReadoutInterface,
    "sample",
    "resistance",
)

NETWORK_SWEEP = declared_interface_ref(NetworkSweepInterface)
NETWORK_SWEEP_START_FREQUENCY = declared_property_ref(
    NetworkSweepState,
    "start_frequency",
)
NETWORK_SWEEP_STOP_FREQUENCY = declared_property_ref(
    NetworkSweepState,
    "stop_frequency",
)
NETWORK_SWEEP_POINTS = declared_property_ref(NetworkSweepState, "points")
NETWORK_SWEEP_IF_BANDWIDTH = declared_property_ref(
    NetworkSweepState,
    "if_bandwidth",
)
NETWORK_SWEEP_SOURCE_POWER = declared_property_ref(
    NetworkSweepState,
    "source_power",
)
NETWORK_SWEEP_S_PARAMETER = declared_property_ref(
    NetworkSweepState,
    "s_parameter",
)
NETWORK_SWEEP_ACQUISITION = declared_acquisition_ref(
    NetworkSweepInterface,
    "sweep",
)
NETWORK_SWEEP_FREQUENCY_RESULT = declared_result_ref(
    NetworkSweepInterface,
    "sweep",
    "frequency",
)
NETWORK_SWEEP_S_PARAMETER_RESULT = declared_result_ref(
    NetworkSweepInterface,
    "sweep",
    "s_parameter",
)

__all__ = [
    "DC_MONITOR",
    "DC_MONITOR_ACQUISITION",
    "DC_MONITOR_CURRENT_RESULT",
    "DC_MONITOR_INTEGRATION_CYCLES",
    "DC_MONITOR_MEASUREMENT_DELAY",
    "DC_MONITOR_MEASUREMENT_ENABLED",
    "DC_MONITOR_VOLTAGE_RESULT",
    "DC_SOURCE",
    "DC_SOURCE_CURRENT_LEVEL",
    "DC_SOURCE_CURRENT_PROTECTION",
    "DC_SOURCE_CURRENT_RANGE",
    "DC_SOURCE_MODE",
    "DC_SOURCE_OUTPUT_ENABLED",
    "DC_SOURCE_VOLTAGE_LEVEL",
    "DC_SOURCE_VOLTAGE_PROTECTION",
    "DC_SOURCE_VOLTAGE_RANGE",
    "NETWORK_SWEEP",
    "NETWORK_SWEEP_ACQUISITION",
    "NETWORK_SWEEP_FREQUENCY_RESULT",
    "NETWORK_SWEEP_IF_BANDWIDTH",
    "NETWORK_SWEEP_POINTS",
    "NETWORK_SWEEP_SOURCE_POWER",
    "NETWORK_SWEEP_START_FREQUENCY",
    "NETWORK_SWEEP_STOP_FREQUENCY",
    "NETWORK_SWEEP_S_PARAMETER",
    "NETWORK_SWEEP_S_PARAMETER_RESULT",
    "RF_OUTPUT",
    "RF_OUTPUT_ENABLED",
    "RF_OUTPUT_FREQUENCY",
    "RF_OUTPUT_POWER",
    "RF_OUTPUT_REFERENCE_SOURCE",
    "TEMPERATURE_READOUT",
    "TEMPERATURE_READOUT_AUTOSCAN_ENABLED",
    "TEMPERATURE_READOUT_RESISTANCE_RESULT",
    "TEMPERATURE_READOUT_SAMPLE",
    "TEMPERATURE_READOUT_SCAN_CHANNEL",
    "TEMPERATURE_READOUT_TEMPERATURE_RESULT",
]

"""Typed identities for the first-party instrument interfaces."""

from __future__ import annotations

from scopecat.sdk.instruments import InterfaceRef
from scopecat.sdk.instruments.declarations import (
    declared_acquisition_ref,
    declared_property_ref,
    declared_result_ref,
)

from scopecat_instruments.interface_declarations import (
    NETWORK_SWEEP_DECLARATION,
    RF_OUTPUT_DECLARATION,
    NetworkSweepInterface,
    NetworkSweepState,
    RFOutputState,
)

RF_OUTPUT = RF_OUTPUT_DECLARATION.ref
RF_OUTPUT_FREQUENCY = declared_property_ref(RFOutputState, "frequency")
RF_OUTPUT_POWER = declared_property_ref(RFOutputState, "power")
RF_OUTPUT_ENABLED = declared_property_ref(RFOutputState, "output_enabled")
RF_OUTPUT_REFERENCE_SOURCE = declared_property_ref(
    RFOutputState,
    "reference_source",
)

DC_SOURCE = InterfaceRef("scopecat.dc_source/v2")
DC_SOURCE_MODE = DC_SOURCE.property("source_mode")
DC_SOURCE_VOLTAGE_RANGE = DC_SOURCE.property("voltage_range")
DC_SOURCE_CURRENT_RANGE = DC_SOURCE.property("current_range")
DC_SOURCE_VOLTAGE_LEVEL = DC_SOURCE.property("voltage_level")
DC_SOURCE_CURRENT_LEVEL = DC_SOURCE.property("current_level")
DC_SOURCE_VOLTAGE_PROTECTION = DC_SOURCE.property("voltage_protection")
DC_SOURCE_CURRENT_PROTECTION = DC_SOURCE.property("current_protection")
DC_SOURCE_OUTPUT_ENABLED = DC_SOURCE.property("output_enabled")

DC_MONITOR = InterfaceRef("scopecat.dc_monitor/v3")
DC_MONITOR_MEASUREMENT_ENABLED = DC_MONITOR.property("measurement_enabled")
DC_MONITOR_INTEGRATION_CYCLES = DC_MONITOR.property("integration_cycles")
DC_MONITOR_MEASUREMENT_DELAY = DC_MONITOR.property("measurement_delay")
DC_MONITOR_ACQUISITION = DC_MONITOR.acquisition("monitor")
DC_MONITOR_CURRENT_RESULT = DC_MONITOR_ACQUISITION.result("monitored_current")
DC_MONITOR_VOLTAGE_RESULT = DC_MONITOR_ACQUISITION.result("monitored_voltage")

TEMPERATURE_READOUT = InterfaceRef("scopecat.temperature_readout/v1")
TEMPERATURE_READOUT_SCAN_CHANNEL = TEMPERATURE_READOUT.property("scan_channel")
TEMPERATURE_READOUT_AUTOSCAN_ENABLED = TEMPERATURE_READOUT.property("autoscan_enabled")
TEMPERATURE_READOUT_SAMPLE = TEMPERATURE_READOUT.acquisition("sample")
TEMPERATURE_READOUT_TEMPERATURE_RESULT = TEMPERATURE_READOUT_SAMPLE.result(
    "temperature"
)
TEMPERATURE_READOUT_RESISTANCE_RESULT = TEMPERATURE_READOUT_SAMPLE.result("resistance")

NETWORK_SWEEP = NETWORK_SWEEP_DECLARATION.ref
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

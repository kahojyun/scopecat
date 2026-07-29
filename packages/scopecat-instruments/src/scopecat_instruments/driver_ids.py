"""Stable driver identifiers without importing driver implementations."""

YOKOGAWA_GS200 = "scopecat.yokogawa.gs200"
ROHDE_SCHWARZ_SGS100A = "scopecat.rohde_schwarz.sgs100a"
LAKESHORE_372 = "scopecat.lakeshore.372"
KEYSIGHT_E5080B = "scopecat.keysight.e5080b"
VIRTUAL_RF_SOURCE = "scopecat.virtual.rf_source"
VIRTUAL_DC_SOURCE = "scopecat.virtual.dc_source"
VIRTUAL_TEMPERATURE_MONITOR = "scopecat.virtual.temperature_monitor"
VIRTUAL_VNA = "scopecat.virtual.vna"

__all__ = [
    "KEYSIGHT_E5080B",
    "LAKESHORE_372",
    "ROHDE_SCHWARZ_SGS100A",
    "VIRTUAL_DC_SOURCE",
    "VIRTUAL_RF_SOURCE",
    "VIRTUAL_TEMPERATURE_MONITOR",
    "VIRTUAL_VNA",
    "YOKOGAWA_GS200",
]

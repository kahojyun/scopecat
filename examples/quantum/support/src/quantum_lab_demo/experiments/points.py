"""Shared typed point values used by modules, templates, and notebooks."""

from __future__ import annotations

import scopecat as sc

_QUBIT = sc.ScalarType(sc.EntityType(entity_kind="logical_qubit"))
_POSITIVE_INT = sc.ScalarType(sc.IntType(minimum=1))
_QUANTITY = sc.ScalarType(sc.QuantityType())

CLIFFORD_COUNT = sc.point("clifford_count", _POSITIVE_INT)
COUPLER_AMPLITUDE = sc.point("coupler_amplitude", _QUANTITY)
COUPLER_DURATION = sc.point("coupler_duration", _QUANTITY)
COUPLER_PARKING_FLUX = sc.point("parking_flux", _QUANTITY)
DRIVE_LENGTH = sc.point("drive_length", _QUANTITY)
GATE_DURATION = sc.point("gate_duration", _QUANTITY)
PHASE_OFFSET = sc.point("phase_offset", _QUANTITY)
QUBIT = sc.point("qubit", _QUBIT)
READOUT_FREQUENCY = sc.point("readout_frequency", _QUANTITY)

__all__ = [
    "CLIFFORD_COUNT",
    "COUPLER_AMPLITUDE",
    "COUPLER_DURATION",
    "COUPLER_PARKING_FLUX",
    "DRIVE_LENGTH",
    "GATE_DURATION",
    "PHASE_OFFSET",
    "QUBIT",
    "READOUT_FREQUENCY",
]

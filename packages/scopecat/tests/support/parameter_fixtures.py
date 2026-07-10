from __future__ import annotations

from scopecat._relations import ParameterRelationData
from scopecat.models.parameter import Quantity


def parameters() -> ParameterRelationData:
    return ParameterRelationData(
        tables={
            "readout_devices": [
                {
                    "device_id": "r0",
                    "enabled": True,
                    "resource_id": "readout-a",
                    "frequency": Quantity(value=5.95, unit="GHz"),
                },
                {
                    "device_id": "r1",
                    "enabled": False,
                    "resource_id": "readout-b",
                    "frequency": Quantity(value=6.10, unit="GHz"),
                },
            ],
            "drive_channels": [
                {
                    "resource_id": "xy0",
                    "fixed_if": Quantity(value=100, unit="MHz"),
                },
                {
                    "resource_id": "xy1",
                    "fixed_if": Quantity(value=120, unit="MHz"),
                },
            ],
        },
    )

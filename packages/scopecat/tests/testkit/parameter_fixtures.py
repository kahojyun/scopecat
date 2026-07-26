from __future__ import annotations

from scopecat.compiler.relations.context import ParameterRelationData
from scopecat.graph.relations.model import ParameterLookupUse
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_types import Bool, Scalar, String, Table, TableColumn
from scopecat.kernel.value_types import Quantity as QuantityType

READOUT_DEVICES_TYPE = Table(
    columns=(
        TableColumn("device_id", Scalar(String())),
        TableColumn("enabled", Scalar(Bool())),
        TableColumn("resource_id", Scalar(String())),
        TableColumn("frequency", Scalar(QuantityType(unit="GHz"))),
    ),
    primary_key=("device_id",),
)
DRIVE_CHANNELS_TYPE = Table(
    columns=(
        TableColumn("resource_id", Scalar(String())),
        TableColumn("fixed_if", Scalar(QuantityType(unit="MHz"))),
    ),
    primary_key=("resource_id",),
)
PARAMETER_TYPES = {
    "drive_channels": DRIVE_CHANNELS_TYPE,
    "readout_devices": READOUT_DEVICES_TYPE,
}
READOUT_FREQUENCY_LOOKUP = ParameterLookupUse(
    table_id="readout_devices",
    key_input_types=(("device_id", Scalar(String())),),
    literal_key_columns=frozenset(),
    column_id="frequency",
    result_type=Scalar(QuantityType(unit="GHz")),
)


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

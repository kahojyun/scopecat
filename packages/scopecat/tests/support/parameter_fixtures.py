from __future__ import annotations

import hashlib
import json

from scopecat.models.parameter import (
    ParameterTable,
    ParameterValue,
    ParameterViewSnapshot,
    Quantity,
)
from scopecat.parameters import (
    ParameterDerivationSet,
    ScalarParameterDerivation,
    TableParameterDerivation,
)
from scopecat.relations import col, param, table


def parameter_view() -> ParameterViewSnapshot:
    return ParameterViewSnapshot(
        id="build",
        catalog_id="catalog",
        catalog_hash=hash_value("catalog"),
        source_state_id="state",
        source_state_hash=hash_value("state"),
        content_hash=hash_value("build"),
        view_implementation_id="test",
        view_implementation_version="v1",
        tables=[
            ParameterTable(
                id="readout_devices",
                rows=[
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
            ),
            ParameterTable(
                id="drive_channels",
                rows=[
                    {
                        "resource_id": "xy0",
                        "fixed_if": Quantity(value=100, unit="MHz"),
                    },
                    {
                        "resource_id": "xy1",
                        "fixed_if": Quantity(value=120, unit="MHz"),
                    },
                ],
            ),
        ],
    )


def derived_parameter_view() -> ParameterViewSnapshot:
    return ParameterViewSnapshot(
        id="derived-build",
        catalog_id="catalog",
        catalog_hash=hash_value("catalog"),
        source_state_id="state",
        source_state_hash=hash_value("state"),
        derivation_set_id="drive-derivations",
        derivation_set_hash=hash_value("derivations"),
        content_hash=hash_value("build"),
        view_implementation_id="test",
        view_implementation_version="v1",
        scalar_values=[
            ParameterValue(
                id="drive.lo_frequency",
                quantity=Quantity(value=4.9, unit="GHz"),
            ),
            ParameterValue(
                id="drive.center_frequency",
                quantity=Quantity(value=5.0, unit="GHz"),
            ),
        ],
        tables=[
            ParameterTable(
                id="drive_channels",
                rows=[
                    {
                        "channel_id": "xy0",
                        "resource_id": "drive-a",
                        "fixed_if": Quantity(value=100, unit="MHz"),
                    },
                    {
                        "channel_id": "xy1",
                        "resource_id": "drive-b",
                        "fixed_if": Quantity(value=120, unit="MHz"),
                    },
                ],
            ),
            ParameterTable(
                id="drive_plan",
                rows=[
                    {
                        "channel_id": "xy0",
                        "resource_id": "drive-a",
                        "carrier_frequency": Quantity(value=5.0, unit="GHz"),
                    },
                    {
                        "channel_id": "xy1",
                        "resource_id": "drive-b",
                        "carrier_frequency": Quantity(value=5.02, unit="GHz"),
                    },
                ],
            ),
        ],
    )


def drive_derivations() -> ParameterDerivationSet:
    return ParameterDerivationSet(
        id="drive-derivations",
        scalars=[
            ScalarParameterDerivation(
                id="drive.center_frequency",
                expression=param("drive.lo_frequency")
                + Quantity(value=100, unit="MHz"),
            )
        ],
        tables=[
            TableParameterDerivation(
                id="drive_plan",
                relation=table("drive_channels")
                .with_columns(
                    carrier_frequency=param("drive.lo_frequency") + col("fixed_if")
                )
                .select("channel_id", "resource_id", "carrier_frequency"),
            )
        ],
    )


def hash_value(value: str) -> str:
    repeated = (value * 64)[:64]
    return f"sha256:{repeated}"


def payload_hash(payload: dict[str, object]) -> str:
    content = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def is_sha256(value: str) -> bool:
    prefix = "sha256:"
    return value.startswith(prefix) and len(value.removeprefix(prefix)) == 64


def diagnostic_codes(diagnostics: list[dict[str, object]]) -> list[str]:
    return [str(item["code"]) for item in diagnostics]

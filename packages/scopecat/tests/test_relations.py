import pytest

from scopecat.models.parameter import (
    ParameterBuildSnapshot,
    ParameterTable,
    ParameterValue,
    Quantity,
)
from scopecat.relations import (
    ParameterRelationData,
    col,
    grid,
    linspace,
    literal_rows,
    outer,
    param,
    parameter_table,
    table,
    values,
)
from tests.support.records import assert_model_round_trip


def test_quantity_converts_and_combines_compatible_units() -> None:
    assert Quantity(value=1000, unit="MHz").to("GHz") == Quantity(
        value=1,
        unit="GHz",
    )
    assert Quantity(value=5.0, unit="GHz") - Quantity(value=100.0, unit="MHz") == (
        Quantity(value=4.9, unit="GHz")
    )

    with pytest.raises(ValueError, match="cannot convert"):
        Quantity(value=1.0, unit="GHz").to("ns")


def test_relation_grid_filter_select_and_round_trip() -> None:
    relation = (
        grid(
            device=literal_rows(
                [
                    {"device_id": "q0", "enabled": True},
                    {"device_id": "q1", "enabled": False},
                ]
            ),
            frequency=linspace(5.0, 5.2, 3, unit="GHz"),
        )
        .filter(col("device.enabled").eq(True))
        .with_columns(detuning=col("frequency") - Quantity(value=100, unit="MHz"))
        .select("device.device_id", "frequency", "detuning")
    )

    restored = assert_model_round_trip(relation)
    rows = restored.evaluate()

    assert rows == [
        {
            "device.device_id": "q0",
            "frequency": Quantity(value=5.0, unit="GHz"),
            "detuning": Quantity(value=4.9, unit="GHz"),
        },
        {
            "device.device_id": "q0",
            "frequency": Quantity(value=5.1, unit="GHz"),
            "detuning": Quantity(value=5.0, unit="GHz"),
        },
        {
            "device.device_id": "q0",
            "frequency": Quantity(value=5.2, unit="GHz"),
            "detuning": Quantity(value=5.1, unit="GHz"),
        },
    ]


def test_parameter_build_snapshot_drives_variable_key_lookup_and_joins() -> None:
    params = ParameterBuildSnapshot(
        id="readout-build",
        catalog_id="catalog",
        catalog_hash=_hash("catalog"),
        source_state_id="state",
        source_state_hash=_hash("state"),
        content_hash=_hash("build"),
        build_implementation_id="test",
        build_implementation_version="v1",
        scalar_values=[
            ParameterValue(
                id="readout.demod_frequency",
                quantity=Quantity(value=100, unit="MHz"),
            )
        ],
        tables=[
            ParameterTable(
                id="readout_devices",
                rows=[
                    {
                        "device_id": "r0",
                        "enabled": True,
                        "resource_id": "adc0",
                        "frequency": Quantity(value=5.95, unit="GHz"),
                    },
                    {
                        "device_id": "r1",
                        "enabled": False,
                        "resource_id": "adc1",
                        "frequency": Quantity(value=6.10, unit="GHz"),
                    },
                ],
            )
        ],
    )

    relation = (
        parameter_table("readout_devices")
        .filter(col("enabled").eq(True))
        .with_columns(
            demod=param("readout.demod_frequency"),
            carrier=param(
                "readout_devices",
                key={"device_id": col("device_id")},
                column="frequency",
            ),
        )
        .select("device_id", "resource_id", "demod", "carrier")
    )

    assert relation.evaluate(params) == [
        {
            "device_id": "r0",
            "resource_id": "adc0",
            "demod": Quantity(value=100, unit="MHz"),
            "carrier": Quantity(value=5.95, unit="GHz"),
        }
    ]


def test_parameter_table_root_is_durable_table_relation() -> None:
    relation = parameter_table("readout_devices")
    restored = assert_model_round_trip(relation)

    assert restored == table("readout_devices")


def test_relation_join_sort_and_limit_are_durable_operations() -> None:
    relation = (
        literal_rows(
            [
                {"device_id": "r1", "frequency": Quantity(value=6.1, unit="GHz")},
                {"device_id": "r0", "frequency": Quantity(value=5.9, unit="GHz")},
            ]
        )
        .join(
            literal_rows(
                [
                    {"device_id": "r0", "resource_id": "adc0"},
                    {"device_id": "r1", "resource_id": "adc1"},
                ]
            ),
            on={"device_id": "device_id"},
        )
        .sort("resource_id")
        .limit(1)
    )

    restored = assert_model_round_trip(relation)

    assert restored.evaluate() == [
        {
            "device_id": "r0",
            "frequency": Quantity(value=5.9, unit="GHz"),
            "resource_id": "adc0",
        }
    ]


def test_outer_scope_supports_repeated_state_style_bindings() -> None:
    params = ParameterRelationData(
        tables={
            "drive_channels": [
                {
                    "resource_id": "xy0",
                    "fixed_if": Quantity(value=100, unit="MHz"),
                },
                {
                    "resource_id": "xy1",
                    "fixed_if": Quantity(value=120, unit="MHz"),
                },
            ]
        }
    )

    repeated = table("drive_channels").with_columns(
        carrier=outer("lo_frequency") + col("fixed_if")
    )

    assert repeated.evaluate(
        params,
        outer_row={"lo_frequency": Quantity(value=5.0, unit="GHz")},
    ) == [
        {
            "resource_id": "xy0",
            "fixed_if": Quantity(value=100, unit="MHz"),
            "carrier": Quantity(value=5.1, unit="GHz"),
        },
        {
            "resource_id": "xy1",
            "fixed_if": Quantity(value=120, unit="MHz"),
            "carrier": Quantity(value=5.12, unit="GHz"),
        },
    ]


def test_values_rejects_non_numeric_unit_items() -> None:
    with pytest.raises(ValueError):
        grid(axis=values(["bad"], unit="GHz"))


def _hash(value: str) -> str:
    repeated = (value * 64)[:64]
    return f"sha256:{repeated}"

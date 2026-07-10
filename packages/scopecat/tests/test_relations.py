import pytest

from scopecat.models.entity import EntityRef
from scopecat.models.parameter import (
    ParameterTable,
    ParameterValue,
    ParameterViewSnapshot,
    Quantity,
)
from scopecat.relations import (
    ParameterRelationData,
    ScalarExpr,
    col,
    grid,
    input_series,
    input_table,
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


def test_parameter_view_snapshot_drives_variable_key_lookup_and_joins() -> None:
    params = ParameterViewSnapshot(
        id="readout-build",
        catalog_id="catalog",
        catalog_hash=_hash("catalog"),
        source_state_id="state",
        source_state_hash=_hash("state"),
        content_hash=_hash("build"),
        view_implementation_id="test",
        view_implementation_version="v1",
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


def test_series_and_table_inputs_are_durable_typed_expressions() -> None:
    rows = [
        {"qubit": "q0", "frequency": Quantity(value=5.0, unit="GHz")},
        {"qubit": "q1", "frequency": Quantity(value=5.1, unit="GHz")},
    ]
    relation = assert_model_round_trip(
        input_table("gate_rows").filter(col("qubit").eq("q1"))
    )
    series = assert_model_round_trip(input_series("offsets"))

    assert relation.evaluate(inputs={"gate_rows": rows}) == [rows[1]]
    assert series.evaluate(
        ParameterRelationData().to_context(
            inputs={
                "offsets": [
                    Quantity(value=-10.0, unit="MHz"),
                    Quantity(value=10.0, unit="MHz"),
                ]
            }
        )
    ) == [
        Quantity(value=-10.0, unit="MHz"),
        Quantity(value=10.0, unit="MHz"),
    ]


def test_relation_column_and_entities_series_have_explicit_ordering_rules() -> None:
    relation = literal_rows(
        [
            {"control": "q0", "partner": "q1"},
            {"control": "q1", "partner": "q2"},
        ]
    )

    column = assert_model_round_trip(relation.column("control"))
    entities = assert_model_round_trip(relation.entities("control", "partner"))
    ctx = ParameterRelationData().to_context()

    assert column.evaluate(ctx) == ["q0", "q1"]
    assert entities.evaluate(ctx) == ["q0", "q1", "q2"]


def test_record_with_entities_field_round_trips_without_collection_coercion() -> None:
    expression = ScalarExpr(
        kind="literal",
        value={
            "entities": [{"id": "q0"}, {"id": "q1"}],
            "kind": "batch",
        },
    )

    restored = assert_model_round_trip(expression)

    assert type(restored.value) is dict
    assert restored.value == {
        "entities": [{"id": "q0"}, {"id": "q1"}],
        "kind": "batch",
    }

    table_rows = input_table("rows").evaluate(
        inputs={
            "rows": [
                {
                    "payload": {
                        "entities": [{"id": "q0"}, {"id": "q1"}],
                        "kind": "batch",
                    }
                }
            ]
        }
    )
    assert type(table_rows[0]["payload"]) is dict
    assert table_rows[0]["payload"] == restored.value


def test_entity_series_round_trips_as_series_shape() -> None:
    series = values(
        [
            EntityRef(id="q0", kind="logical_device"),
            EntityRef(id="q1", kind="logical_device"),
        ]
    )

    restored = assert_model_round_trip(series)

    assert restored.evaluate(ParameterRelationData().to_context()) == [
        EntityRef(id="q0", kind="logical_device"),
        EntityRef(id="q1", kind="logical_device"),
    ]


def test_cross_evaluates_right_relation_with_left_row_context() -> None:
    relation = grid(qubit=["q0", "q1"]).cross(
        grid(
            frequency=linspace(
                param(
                    "qubits",
                    key={"qubit": col("qubit")},
                    column="center_frequency",
                )
                - Quantity(value=100, unit="MHz"),
                param(
                    "qubits",
                    key={"qubit": col("qubit")},
                    column="center_frequency",
                )
                + Quantity(value=100, unit="MHz"),
                3,
            )
        )
    )
    params = ParameterRelationData(
        tables={
            "qubits": [
                {
                    "qubit": "q0",
                    "center_frequency": Quantity(value=5.0, unit="GHz"),
                },
                {
                    "qubit": "q1",
                    "center_frequency": Quantity(value=6.0, unit="GHz"),
                },
            ]
        }
    )

    assert relation.evaluate(params) == [
        {"qubit": "q0", "frequency": Quantity(value=4.9, unit="GHz")},
        {"qubit": "q0", "frequency": Quantity(value=5.0, unit="GHz")},
        {"qubit": "q0", "frequency": Quantity(value=5.1, unit="GHz")},
        {"qubit": "q1", "frequency": Quantity(value=5.9, unit="GHz")},
        {"qubit": "q1", "frequency": Quantity(value=6.0, unit="GHz")},
        {"qubit": "q1", "frequency": Quantity(value=6.1, unit="GHz")},
    ]


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

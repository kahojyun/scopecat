import pytest

from scopecat.compiler.relations.evaluation import ParameterRelationData
from scopecat.compiler.relations.model import (
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
    range_values,
    table,
    values,
)
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.kernel.value_types import (
    Bool,
    Record,
    RecordField,
    Scalar,
    Series,
    String,
    Table,
    TableColumn,
)
from scopecat.kernel.value_types import (
    Quantity as QuantityType,
)
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity
from tests.testkit.records import assert_model_round_trip
from tests.testkit.relation_plans import evaluate_relation, evaluate_series

_BOOL = Scalar(Bool())
_STRING = Scalar(String())
_FREQUENCY = Scalar(QuantityType(dimension="frequency"))


def _table_type(**columns: Scalar) -> Table:
    return Table(
        tuple(TableColumn(name, value_type) for name, value_type in columns.items())
    )


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


def test_series_materialization_enforces_finiteness_and_progress() -> None:
    ctx = ParameterRelationData().to_context()

    with pytest.raises(ValueError, match="non-finite"):
        evaluate_series(
            linspace(-1e308, 1e308, 3),
            ctx,
        )
    with pytest.raises(ValueError, match="too small to advance"):
        evaluate_series(
            range_values(1e308, 1.1e308, 1e-300),
            ctx,
        )


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
    rows = evaluate_relation(restored)

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


def test_parameter_data_drives_variable_key_lookup_and_joins() -> None:
    params = ParameterRelationData(
        scalars={
            "readout.demod_frequency": Quantity(value=100, unit="MHz"),
        },
        tables={
            "readout_devices": [
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
        },
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

    assert evaluate_relation(
        relation,
        params,
        bindings=RelationTypeBindings(
            parameters={
                "readout.demod_frequency": _FREQUENCY,
                "readout_devices": _table_type(
                    device_id=_STRING,
                    enabled=_BOOL,
                    resource_id=_STRING,
                    frequency=_FREQUENCY,
                ),
            }
        ),
    ) == [
        {
            "device_id": "r0",
            "resource_id": "adc0",
            "demod": Quantity(value=100, unit="MHz"),
            "carrier": Quantity(value=5.95, unit="GHz"),
        }
    ]


def test_parameter_lookup_matches_entity_refs_by_stable_identity() -> None:
    params = ParameterRelationData(
        tables={
            "qubits": [
                {
                    "qubit": EntityRef(id="q0", kind="qubit"),
                    "frequency": Quantity(value=5.0, unit="GHz"),
                }
            ]
        }
    )

    row = params.lookup_row(
        "qubits",
        {
            "qubit": EntityRef(
                id="q0",
                kind="qubit",
                metadata={"source": "lookup"},
            )
        },
    )

    assert row["frequency"] == Quantity(value=5.0, unit="GHz")
    with pytest.raises(ValueError, match="matched 0 rows"):
        params.lookup_row("qubits", {"qubit": EntityRef(id="q0")})


def test_parameter_lookup_matches_compatible_quantity_units() -> None:
    params = ParameterRelationData(
        tables={
            "frequencies": [
                {
                    "frequency": Quantity(value=5000.0, unit="MHz"),
                    "label": "q0",
                }
            ]
        }
    )

    assert (
        params.lookup_row(
            "frequencies",
            {"frequency": Quantity(value=5.0, unit="GHz")},
        )["label"]
        == "q0"
    )


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

    assert evaluate_relation(
        relation,
        inputs={"gate_rows": rows},
        bindings=RelationTypeBindings(
            inputs={
                "gate_rows": _table_type(
                    qubit=_STRING,
                    frequency=_FREQUENCY,
                )
            }
        ),
    ) == [rows[1]]
    assert evaluate_series(
        series,
        ParameterRelationData().to_context(
            inputs={
                "offsets": [
                    Quantity(value=-10.0, unit="MHz"),
                    Quantity(value=10.0, unit="MHz"),
                ]
            }
        ),
        bindings=RelationTypeBindings(inputs={"offsets": Series(_FREQUENCY)}),
    ) == [
        Quantity(value=-10.0, unit="MHz"),
        Quantity(value=10.0, unit="MHz"),
    ]


def test_relation_column_and_entities_series_have_explicit_ordering_rules() -> None:
    q0 = EntityRef(id="q0", kind="qubit")
    q1 = EntityRef(id="q1", kind="qubit")
    q2 = EntityRef(id="q2", kind="qubit")
    relation = literal_rows(
        [
            {"control": q0, "partner": q1},
            {"control": q1, "partner": q2},
        ]
    )

    column = assert_model_round_trip(relation.column("control"))
    entities = assert_model_round_trip(relation.entities("control", "partner"))
    ctx = ParameterRelationData().to_context()

    assert evaluate_series(column, ctx) == [q0, q1]
    assert evaluate_series(entities, ctx) == [
        q0,
        q1,
        q2,
    ]


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

    table_rows = evaluate_relation(
        input_table("rows"),
        inputs={
            "rows": [
                {
                    "payload": {
                        "entities": [{"id": "q0"}, {"id": "q1"}],
                        "kind": "batch",
                    }
                }
            ]
        },
        bindings=RelationTypeBindings(
            inputs={
                "rows": _table_type(
                    payload=Scalar(
                        Record(
                            fields=(
                                RecordField(
                                    "entities",
                                    Series(
                                        Scalar(
                                            Record(fields=(RecordField("id", _STRING),))
                                        )
                                    ),
                                ),
                                RecordField("kind", _STRING),
                            )
                        )
                    )
                )
            }
        ),
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

    assert evaluate_series(
        restored,
        ParameterRelationData().to_context(),
    ) == [
        EntityRef(id="q0", kind="logical_device"),
        EntityRef(id="q1", kind="logical_device"),
    ]


def test_lateral_cross_evaluates_right_relation_with_left_row_context() -> None:
    relation = grid(qubit=["q0", "q1"]).lateral_cross(
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

    assert evaluate_relation(
        relation,
        params,
        bindings=RelationTypeBindings(
            parameters={
                "qubits": _table_type(
                    qubit=_STRING,
                    center_frequency=_FREQUENCY,
                )
            }
        ),
    ) == [
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

    assert evaluate_relation(restored) == [
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

    assert evaluate_relation(
        repeated,
        params,
        outer_row={"lo_frequency": Quantity(value=5.0, unit="GHz")},
        bindings=RelationTypeBindings(
            parameters={
                "drive_channels": _table_type(
                    resource_id=_STRING,
                    fixed_if=_FREQUENCY,
                )
            },
            outer_row=RowType((TableColumn("lo_frequency", _FREQUENCY),)),
        ),
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

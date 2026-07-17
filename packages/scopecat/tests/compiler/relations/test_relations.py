import pytest

from scopecat.compiler.relations.evaluation import ParameterRelationData
from scopecat.compiler.relations.model import (
    BinaryScalarExpr,
    CaseScalarExpr,
    ColumnScalarExpr,
    GridRelationExpr,
    InputScalarExpr,
    InputSeriesExpr,
    JoinRelationExpr,
    LimitRelationExpr,
    LinspaceSeriesExpr,
    LiteralScalarExpr,
    OuterColumnScalarExpr,
    ParameterLookupScalarExpr,
    ParameterScalarExpr,
    ParameterSeriesExpr,
    PointColumnScalarExpr,
    RangeSeriesExpr,
    RelationColumnSeriesExpr,
    RelationEntitiesSeriesExpr,
    ScalarGridColumn,
    SelectRelationExpr,
    SeriesGridColumn,
    SortRelationExpr,
    TableRelationExpr,
    ValuesSeriesExpr,
    WithColumnsRelationExpr,
    case,
    col,
    grid,
    input_ref,
    input_series,
    input_table,
    linspace,
    lit,
    literal_rows,
    outer,
    param,
    parameter_series,
    point_col,
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


def test_relation_grid_filter_select() -> None:
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

    rows = evaluate_relation(relation)

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
        table("readout_devices")
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


def test_series_and_table_inputs_are_typed_expressions() -> None:
    rows = [
        {"qubit": "q0", "frequency": Quantity(value=5.0, unit="GHz")},
        {"qubit": "q1", "frequency": Quantity(value=5.1, unit="GHz")},
    ]
    relation = input_table("gate_rows").filter(col("qubit").eq("q1"))
    series = input_series("offsets")

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


def test_grid_preserves_concrete_series_variants() -> None:
    source = literal_rows([{"value": 1, "entity": EntityRef(id="q0", kind="qubit")}])
    relation = grid(
        literal=values([1]),
        evenly_spaced=linspace(0, 1, 2),
        stepped=range_values(0, 2, 1),
        input=input_series("samples"),
        parameter=parameter_series("frequencies"),
        column=source.column("value"),
        entities=source.entities("entity"),
    )

    series = [
        column.series
        for column in relation.columns.values()
        if isinstance(column, SeriesGridColumn)
    ]
    assert [type(expression) for expression in series] == [
        ValuesSeriesExpr,
        LinspaceSeriesExpr,
        RangeSeriesExpr,
        InputSeriesExpr,
        ParameterSeriesExpr,
        RelationColumnSeriesExpr,
        RelationEntitiesSeriesExpr,
    ]


def test_grid_preserves_recursive_scalar_variants() -> None:
    relation = grid(
        literal=lit(None),
        column=col("current"),
        outer=outer("outer"),
        point=point_col("point"),
        input=input_ref("input"),
        parameter=param("scalar"),
        lookup=param("table", key={"id": input_ref("id")}, column="value"),
        binary=input_ref("left") + param("right"),
        case=case(
            (
                input_ref("enabled"),
                input_ref("selected")
                + param("table", key={"id": input_ref("case_id")}, column="value"),
            ),
            fallback=None,
        ),
    )

    scalars = [
        column.scalar
        for column in relation.columns.values()
        if isinstance(column, ScalarGridColumn)
    ]
    assert [type(expression) for expression in scalars] == [
        LiteralScalarExpr,
        ColumnScalarExpr,
        OuterColumnScalarExpr,
        PointColumnScalarExpr,
        InputScalarExpr,
        ParameterScalarExpr,
        ParameterLookupScalarExpr,
        BinaryScalarExpr,
        CaseScalarExpr,
    ]

    lookup = scalars[6]
    assert isinstance(lookup, ParameterLookupScalarExpr)
    assert isinstance(lookup.key["id"], InputScalarExpr)
    binary = scalars[7]
    assert isinstance(binary, BinaryScalarExpr)
    assert isinstance(binary.left, InputScalarExpr)
    assert isinstance(binary.right, ParameterScalarExpr)
    selected = scalars[8]
    assert isinstance(selected, CaseScalarExpr)
    assert isinstance(selected.cases[0].condition, InputScalarExpr)
    case_value = selected.cases[0].value
    assert isinstance(case_value, BinaryScalarExpr)
    assert isinstance(case_value.left, InputScalarExpr)
    assert isinstance(case_value.right, ParameterLookupScalarExpr)
    assert isinstance(case_value.right.key["id"], InputScalarExpr)
    assert isinstance(selected.fallback, LiteralScalarExpr)


def test_relation_variant_fields_preserve_empty_semantics() -> None:
    leaf = literal_rows([])

    assert leaf.rows == []
    assert TableRelationExpr(table_id="").table_id == ""
    assert GridRelationExpr(columns={}).columns == {}
    assert SelectRelationExpr(source=leaf, select_columns=[]).select_columns == []
    assert WithColumnsRelationExpr(source=leaf, new_columns={}).new_columns == {}
    assert JoinRelationExpr(left=leaf, right=leaf, on={"": ""}).on == {"": ""}
    assert SortRelationExpr(source=leaf, sort_columns=[""]).sort_columns == [""]
    assert LimitRelationExpr(source=leaf, limit_count=0).limit_count == 0


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

    column = relation.column("control")
    entities = relation.entities("control", "partner")
    ctx = ParameterRelationData().to_context()

    assert evaluate_series(column, ctx) == [q0, q1]
    assert evaluate_series(entities, ctx) == [
        q0,
        q1,
        q2,
    ]


def test_record_with_entities_field_preserves_collection_shape() -> None:
    expression = LiteralScalarExpr(
        value={
            "entities": [{"id": "q0"}, {"id": "q1"}],
            "kind": "batch",
        },
    )

    assert type(expression.value) is dict
    assert expression.value == {
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
    assert table_rows[0]["payload"] == expression.value


def test_entity_series_preserves_series_shape() -> None:
    series = values(
        [
            EntityRef(id="q0", kind="logical_device"),
            EntityRef(id="q1", kind="logical_device"),
        ]
    )

    assert evaluate_series(
        series,
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


def test_relation_join_sort_and_limit_operations() -> None:
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

    assert evaluate_relation(relation) == [
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
    with pytest.raises(ValueError, match="could not convert string to float"):
        grid(axis=values(["bad"], unit="GHz"))

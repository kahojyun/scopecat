import pytest

from scopecat.compiler.relations.context import EvalContext, ParameterRelationData
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
)
from scopecat.graph.relations.input_binding import (
    bind_relation_input_refs,
    bind_scalar_input_refs,
    bind_series_input_refs,
)
from scopecat.graph.relations.model import (
    LiteralScalarExpr,
    ParameterLookupUse,
    RowScopeId,
    SelectRelationExpr,
    TableRelationExpr,
    WithColumnsRelationExpr,
    col,
    input_ref,
    input_series,
    input_table,
    literal_rows,
    param,
    parameter_lookup,
    table,
    values,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.symbols import SymbolId
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
from tests.testkit.relation_plans import evaluate_relation, evaluate_series

_BOOL = Scalar(Bool())
_STRING = Scalar(String())
_FREQUENCY = Scalar(QuantityType(dimension="frequency"))


def _scope(local_id: str) -> RowScopeId:
    return RowScopeId(SymbolId(local_id=local_id))


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


def test_literal_rows_with_columns_select() -> None:
    columns_scope = _scope("literal-columns")
    relation = (
        literal_rows(
            [
                {
                    "device.device_id": "q0",
                    "frequency": Quantity(value=frequency, unit="GHz"),
                }
                for frequency in (5.0, 5.1, 5.2)
            ]
        )
        .with_columns(
            row_scope_id=columns_scope,
            detuning=col("frequency", row_scope_id=columns_scope)
            - Quantity(value=100, unit="MHz"),
        )
        .select("device.device_id", "frequency", "detuning")
    )

    rows = evaluate_relation(relation, EvalContext())

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

    columns_scope = _scope("parameter-columns")
    relation = (
        table("readout_devices")
        .with_columns(
            row_scope_id=columns_scope,
            demod=param("readout.demod_frequency"),
            carrier=parameter_lookup(
                ParameterLookupUse(
                    table_id="readout_devices",
                    key_input_types=(("device_id", _STRING),),
                    literal_key_columns=frozenset(),
                    column_id="frequency",
                    result_type=_FREQUENCY,
                ),
                key={"device_id": col("device_id", row_scope_id=columns_scope)},
            ),
        )
        .select("device_id", "resource_id", "demod", "carrier")
    )

    assert evaluate_relation(
        relation,
        EvalContext(params=params),
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
        },
        {
            "device_id": "r1",
            "resource_id": "adc1",
            "demod": Quantity(value=100, unit="MHz"),
            "carrier": Quantity(value=6.10, unit="GHz"),
        },
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
    relation = input_table("gate_rows").select("qubit")
    series = input_series("offsets")

    assert evaluate_relation(
        relation,
        EvalContext(inputs={"gate_rows": rows}),
        bindings=RelationTypeBindings(
            inputs={
                "gate_rows": _table_type(
                    qubit=_STRING,
                    frequency=_FREQUENCY,
                )
            }
        ),
    ) == [{"qubit": "q0"}, {"qubit": "q1"}]
    assert evaluate_series(
        series,
        EvalContext(
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


def test_input_binding_preserves_same_named_unresolved_references() -> None:
    scalar = input_ref("value")
    series = input_series("values")
    relation = input_table("rows")

    assert bind_scalar_input_refs(scalar, {"value": scalar}) is scalar
    assert bind_series_input_refs(series, {"values": series}) is series
    assert bind_relation_input_refs(relation, {"rows": relation}) is relation


def test_input_binding_rejects_indirect_cycles() -> None:
    with pytest.raises(ValueError, match="cyclic module input reference"):
        bind_scalar_input_refs(
            input_ref("a"),
            {"a": input_ref("b"), "b": input_ref("a")},
        )
    with pytest.raises(ValueError, match="cyclic module input reference"):
        bind_series_input_refs(
            input_series("a"),
            {"a": input_series("b"), "b": input_series("a")},
        )
    with pytest.raises(ValueError, match="cyclic module input reference"):
        bind_relation_input_refs(
            input_table("a"),
            {"a": input_table("b"), "b": input_table("a")},
        )


def test_relation_variant_fields_preserve_empty_semantics() -> None:
    leaf = literal_rows([])

    assert leaf.rows == []
    assert TableRelationExpr(table_id="").table_id == ""
    assert SelectRelationExpr(source=leaf, select_columns=[]).select_columns == []
    assert (
        WithColumnsRelationExpr(
            source=leaf,
            new_columns={},
            row_scope_id=_scope("empty-columns"),
        ).new_columns
        == {}
    )


def test_relation_entities_series_has_explicit_ordering_rules() -> None:
    q0 = EntityRef(id="q0", kind="qubit")
    q1 = EntityRef(id="q1", kind="qubit")
    q2 = EntityRef(id="q2", kind="qubit")
    relation = literal_rows(
        [
            {"control": q0, "partner": q1},
            {"control": q1, "partner": q2},
        ]
    )

    entities = relation.entities("control", "partner")
    ctx = EvalContext()

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
        EvalContext(
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
        ),
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
        EvalContext(),
    ) == [
        EntityRef(id="q0", kind="logical_device"),
        EntityRef(id="q1", kind="logical_device"),
    ]


def test_values_rejects_non_numeric_unit_items() -> None:
    with pytest.raises(ValueError, match="could not convert string to float"):
        values(["bad"], unit="GHz")

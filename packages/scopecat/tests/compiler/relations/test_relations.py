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
    TableRelationExpr,
    input_ref,
    input_series,
    input_table,
    literal_rows,
    values,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_types import (
    Entity,
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
    assert params.lookup_row("qubits", {"qubit": "q0"}) == row
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
    relation = input_table("gate_rows")
    series = input_series("offsets")

    assert (
        evaluate_relation(
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
        )
        == rows
    )
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
        expected_type=Series(
            Scalar(Entity("logical_device")),
            min_length=2,
            max_length=2,
        ),
    ) == [
        EntityRef(id="q0", kind="logical_device"),
        EntityRef(id="q1", kind="logical_device"),
    ]


def test_values_rejects_non_numeric_unit_items() -> None:
    with pytest.raises(ValueError, match="could not convert string to float"):
        values(["bad"], unit="GHz")

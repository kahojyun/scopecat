import pytest

from scopecat.compiler.relations.context import EvalContext, ParameterRelationData
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
)
from scopecat.graph.relations.input_binding import (
    bind_relation_input_refs,
    bind_scalar_input_refs,
)
from scopecat.graph.relations.model import (
    TableRelationExpr,
    input_ref,
    input_table,
    literal_rows,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_types import (
    Quantity as QuantityType,
)
from scopecat.kernel.value_types import (
    Scalar,
    String,
    Table,
    TableColumn,
)
from tests.testkit.relation_plans import evaluate_relation

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


def test_table_inputs_are_typed_expressions() -> None:
    rows = [
        {"qubit": "q0", "frequency": Quantity(value=5.0, unit="GHz")},
        {"qubit": "q1", "frequency": Quantity(value=5.1, unit="GHz")},
    ]
    relation = input_table("gate_rows")

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


def test_input_binding_preserves_same_named_unresolved_references() -> None:
    scalar = input_ref("value")
    relation = input_table("rows")

    assert bind_scalar_input_refs(scalar, {"value": scalar}) is scalar
    assert bind_relation_input_refs(relation, {"rows": relation}) is relation


def test_input_binding_rejects_indirect_cycles() -> None:
    with pytest.raises(ValueError, match="cyclic module input reference"):
        bind_scalar_input_refs(
            input_ref("a"),
            {"a": input_ref("b"), "b": input_ref("a")},
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

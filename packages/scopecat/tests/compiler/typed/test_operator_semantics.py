from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.authoring._value_refs import (
    internal_lower_scalar_value_ref,
    internal_lower_table_value_ref,
)
from scopecat.compiler.relations.evaluation import ParameterRelationData
from scopecat.compiler.relations.model import (
    lit,
)
from scopecat.compiler.relations.operators import (
    compare_ordered_values,
    runtime_values_equal,
)
from scopecat.compiler.relations.verification import RelationTypeBindings
from tests.testkit.relation_plans import evaluate_relation, evaluate_scalar


def _input_bindings(**inputs: sc.ValueType) -> RelationTypeBindings:
    return RelationTypeBindings(inputs=inputs)


def test_typed_arithmetic_and_runtime_use_the_same_operator_contract() -> None:
    text = sc.input("text", sc.ScalarType(sc.StringType()))
    count = sc.input("count", sc.ScalarType(sc.IntType()))

    with pytest.raises(TypeError, match=r"operator '\+' is not defined"):
        _ = text + "suffix"
    with pytest.raises(TypeError, match="not defined"):
        text.lt(count)

    numeric = count + 0.5
    assert numeric.value_type == sc.ScalarType(sc.FloatType())
    assert (
        evaluate_scalar(
            internal_lower_scalar_value_ref(numeric),
            ParameterRelationData().to_context(inputs={"count": 2}),
            bindings=_input_bindings(count=count.value_type),
        )
        == 2.5
    )


def test_integer_arithmetic_preserves_provable_bounds() -> None:
    count = sc.point(
        "count",
        sc.ScalarType(sc.IntType(minimum=0, maximum=4)),
    )

    assert (2 * count + 1).value_type == sc.ScalarType(sc.IntType(minimum=1, maximum=9))
    assert (3 - count).value_type == sc.ScalarType(sc.IntType(minimum=-1, maximum=3))


def test_typed_arithmetic_rejects_non_finite_runtime_results() -> None:
    value = sc.input("value", sc.ScalarType(sc.FloatType()))
    overflow = internal_lower_scalar_value_ref(value * 1e308)

    with pytest.raises(ValueError, match="non-finite result"):
        evaluate_scalar(
            overflow,
            ParameterRelationData().to_context(inputs={"value": 1e308}),
            bindings=_input_bindings(value=value.value_type),
        )


def test_entity_equality_uses_kind_and_id_but_not_metadata() -> None:
    generic = sc.input("generic", sc.ScalarType(sc.EntityType()))
    qubit = sc.input(
        "qubit",
        sc.ScalarType(sc.EntityType(entity_kind="qubit")),
    )
    resonator = sc.input(
        "resonator",
        sc.ScalarType(sc.EntityType(entity_kind="resonator")),
    )
    comparison = internal_lower_scalar_value_ref(generic.eq(qubit))
    concrete_kind_comparison = internal_lower_scalar_value_ref(resonator.eq(qubit))

    assert (
        evaluate_scalar(
            comparison,
            ParameterRelationData().to_context(
                inputs={
                    "generic": sc.EntityRef(
                        id="q0",
                        kind="qubit",
                        metadata={"source": "left"},
                    ),
                    "qubit": sc.EntityRef(
                        id="q0",
                        kind="qubit",
                        metadata={"source": "right"},
                    ),
                }
            ),
            bindings=_input_bindings(
                generic=generic.value_type,
                qubit=qubit.value_type,
            ),
        )
        is True
    )
    assert (
        evaluate_scalar(
            comparison,
            ParameterRelationData().to_context(
                inputs={
                    "generic": sc.EntityRef(id="q0", kind="resonator"),
                    "qubit": sc.EntityRef(id="q0", kind="qubit"),
                }
            ),
            bindings=_input_bindings(
                generic=generic.value_type,
                qubit=qubit.value_type,
            ),
        )
        is False
    )
    assert (
        evaluate_scalar(
            concrete_kind_comparison,
            ParameterRelationData().to_context(
                inputs={
                    "resonator": sc.EntityRef(id="q0", kind="resonator"),
                    "qubit": sc.EntityRef(id="q0", kind="qubit"),
                }
            ),
            bindings=_input_bindings(
                resonator=resonator.value_type,
                qubit=qubit.value_type,
            ),
        )
        is False
    )


def test_record_equality_recurses_through_typed_scalar_semantics() -> None:
    record_type = sc.ScalarType(
        sc.RecordType(
            fields=(
                sc.RecordField(
                    "entity",
                    sc.ScalarType(sc.EntityType(entity_kind="logical_qubit")),
                ),
                sc.RecordField(
                    "frequency",
                    sc.ScalarType(sc.QuantityType(dimension="frequency")),
                ),
            )
        )
    )
    left = sc.input("left", record_type)
    right = sc.input("right", record_type)
    comparison = internal_lower_scalar_value_ref(left.eq(right))

    assert (
        evaluate_scalar(
            comparison,
            ParameterRelationData().to_context(
                inputs={
                    "left": {
                        "entity": sc.EntityRef(
                            id="q0",
                            kind="logical_qubit",
                            metadata={"source": "left"},
                        ),
                        "frequency": sc.Quantity(5.0, "GHz"),
                    },
                    "right": {
                        "entity": sc.EntityRef(
                            id="q0",
                            kind="logical_qubit",
                            metadata={"source": "right"},
                        ),
                        "frequency": sc.Quantity(5000.0, "MHz"),
                    },
                }
            ),
            bindings=_input_bindings(
                left=left.value_type,
                right=right.value_type,
            ),
        )
        is True
    )


def test_payload_and_open_or_collection_record_types_do_not_claim_equality() -> None:
    payload_type = sc.ScalarType(sc.PayloadType("waveform"))
    payload = sc.input("payload", payload_type)
    with pytest.raises(TypeError, match="not defined"):
        payload.eq(payload)
    with pytest.raises(TypeError, match="not defined"):
        payload.eq(None)

    unsupported_records = (
        sc.RecordType(
            fields=(sc.RecordField("value", sc.ScalarType(sc.IntType())),),
            allow_extra_fields=True,
        ),
        sc.RecordType(
            fields=(
                sc.RecordField(
                    "values",
                    sc.SeriesType(sc.ScalarType(sc.IntType())),
                ),
            ),
        ),
        sc.RecordType(
            fields=(
                sc.RecordField(
                    "nested",
                    sc.ScalarType(
                        sc.RecordType(
                            fields=(sc.RecordField("data", payload_type),),
                        )
                    ),
                ),
            ),
        ),
    )
    for index, record_type in enumerate(unsupported_records):
        left = sc.input(f"left_{index}", sc.ScalarType(record_type))
        right = sc.input(f"right_{index}", sc.ScalarType(record_type))
        with pytest.raises(TypeError, match="closed, recursively scalar"):
            left.eq(right)


def test_nullable_values_are_only_safe_for_equality() -> None:
    optional_count = sc.input(
        "count",
        sc.ScalarType(sc.IntType(), nullable=True),
    )

    with pytest.raises(TypeError, match="does not accept nullable operands"):
        _ = optional_count + 1
    with pytest.raises(TypeError, match="does not accept nullable operands"):
        optional_count.lt(1)

    is_null = optional_count.eq(None)
    assert is_null.value_type == sc.ScalarType(sc.BoolType())
    assert (
        evaluate_scalar(
            internal_lower_scalar_value_ref(is_null),
            ParameterRelationData().to_context(inputs={"count": None}),
            bindings=_input_bindings(count=optional_count.value_type),
        )
        is True
    )


def test_typed_boolean_composition_uses_the_shared_operator_contract() -> None:
    left = sc.input("left", sc.ScalarType(sc.BoolType()))
    right = sc.input("right", sc.ScalarType(sc.BoolType()))

    conjunction = internal_lower_scalar_value_ref(left.and_(right))
    disjunction = internal_lower_scalar_value_ref(left.or_(right))
    context = ParameterRelationData().to_context(inputs={"left": True, "right": False})

    bindings = _input_bindings(left=left.value_type, right=right.value_type)
    assert evaluate_scalar(conjunction, context, bindings=bindings) is False
    assert evaluate_scalar(disjunction, context, bindings=bindings) is True
    with pytest.raises(TypeError, match="not defined"):
        left.and_(1)


def test_quantity_equality_and_order_use_a_symmetric_common_base_unit() -> None:
    tiny_ghz = sc.Quantity(1e-13, "GHz")
    tiny_hz = sc.Quantity(1e-4, "Hz")

    assert runtime_values_equal(tiny_ghz, tiny_hz)
    assert runtime_values_equal(tiny_hz, tiny_ghz)
    assert compare_ordered_values(tiny_ghz, tiny_hz) == 0
    assert compare_ordered_values(tiny_hz, tiny_ghz) == 0


def test_ordering_requires_finite_numeric_contracts_and_values() -> None:
    open_float = sc.input(
        "value",
        sc.ScalarType(sc.FloatType(finite=False)),
    )
    with pytest.raises(TypeError, match="guarantee finite"):
        open_float.lt(1.0)
    with pytest.raises(ValueError, match="Float bounds must be finite"):
        evaluate_scalar(
            lit(float("nan")).lt(1.0),
            ParameterRelationData().to_context(),
        )


def test_table_transforms_only_retain_provable_primary_keys() -> None:
    rows = sc.input(
        "rows",
        sc.TableType(
            columns=(
                sc.TableColumn("group", sc.ScalarType(sc.IntType())),
                sc.TableColumn("item", sc.ScalarType(sc.IntType())),
                sc.TableColumn("value", sc.ScalarType(sc.IntType())),
            ),
            primary_key=("group", "item"),
        ),
    )

    partial = rows.select("group", "value")
    complete = rows.select("item", "group")
    overwritten = rows.with_columns(lambda row: {"item": row["group"]})
    extended = rows.with_columns(lambda row: {"copy": row["value"]})

    assert isinstance(partial.value_type, sc.TableType)
    assert partial.value_type.primary_key == ()
    assert isinstance(complete.value_type, sc.TableType)
    assert complete.value_type.primary_key == ("group", "item")
    assert isinstance(overwritten.value_type, sc.TableType)
    assert overwritten.value_type.primary_key == ()
    assert isinstance(extended.value_type, sc.TableType)
    assert extended.value_type.primary_key == ("group", "item")

    source_rows = [
        {"group": 1, "item": 1, "value": 10},
        {"group": 1, "item": 2, "value": 20},
    ]
    assert evaluate_relation(
        internal_lower_table_value_ref(partial),
        inputs={"rows": source_rows},
        bindings=_input_bindings(rows=rows.value_type),
    ) == [
        {"group": 1, "value": 10},
        {"group": 1, "value": 20},
    ]
    assert evaluate_relation(
        internal_lower_table_value_ref(overwritten),
        inputs={"rows": source_rows},
        bindings=_input_bindings(rows=rows.value_type),
    ) == [
        {"group": 1, "item": 1, "value": 10},
        {"group": 1, "item": 1, "value": 20},
    ]


def test_dotted_table_columns_are_exact_keys_for_row_access() -> None:
    rows = sc.input(
        "rows",
        sc.TableType(
            columns=(
                sc.TableColumn("device.rank", sc.ScalarType(sc.IntType())),
                sc.TableColumn("label", sc.ScalarType(sc.StringType())),
            )
        ),
    )
    transformed = rows.with_columns(lambda row: {"copied_rank": row["device.rank"]})

    assert evaluate_relation(
        internal_lower_table_value_ref(transformed),
        inputs={
            "rows": [
                {"device.rank": 2, "label": "second"},
                {"device.rank": 1, "label": "first"},
            ]
        },
        bindings=_input_bindings(rows=rows.value_type),
    ) == [
        {"device.rank": 2, "label": "second", "copied_rank": 2},
        {"device.rank": 1, "label": "first", "copied_rank": 1},
    ]

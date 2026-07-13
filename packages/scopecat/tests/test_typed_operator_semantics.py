from __future__ import annotations

import pytest

import scopecat as sc
from scopecat._relation_backend import (
    REFERENCE_RELATION_BACKEND,
    ParameterRelationData,
)
from scopecat._relation_verification import RelationTypeBindings
from scopecat._relations import lit, literal_rows
from scopecat._scalar_operators import compare_ordered_values, runtime_values_equal
from scopecat.authoring._value_refs import (
    internal_lower_scalar_value_ref,
    internal_lower_table_value_ref,
)
from tests.support.relation_plans import evaluate_relation, evaluate_scalar

_BACKEND = REFERENCE_RELATION_BACKEND


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
            _BACKEND,
            internal_lower_scalar_value_ref(numeric),
            ParameterRelationData().to_context(inputs={"count": 2}),
            bindings=_input_bindings(count=count.value_type),
        )
        == 2.5
    )


def test_typed_arithmetic_rejects_non_finite_runtime_results() -> None:
    value = sc.input("value", sc.ScalarType(sc.FloatType()))
    overflow = internal_lower_scalar_value_ref(value * 1e308)

    with pytest.raises(ValueError, match="non-finite result"):
        evaluate_scalar(
            _BACKEND,
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
            _BACKEND,
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
            _BACKEND,
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
            _BACKEND,
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
            _BACKEND,
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
            _BACKEND,
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
    assert evaluate_scalar(_BACKEND, conjunction, context, bindings=bindings) is False
    assert evaluate_scalar(_BACKEND, disjunction, context, bindings=bindings) is True
    with pytest.raises(TypeError, match="not defined"):
        left.and_(1)


def test_typed_sort_uses_numeric_string_and_quantity_ordering() -> None:
    rows = sc.input(
        "rows",
        sc.TableType(
            columns=(
                sc.TableColumn("number", sc.ScalarType(sc.IntType())),
                sc.TableColumn("label", sc.ScalarType(sc.StringType())),
                sc.TableColumn(
                    "frequency",
                    sc.ScalarType(sc.QuantityType(dimension="frequency")),
                ),
            )
        ),
    )
    sorted_rows = evaluate_relation(
        _BACKEND,
        internal_lower_table_value_ref(rows.sort("number", "label", "frequency")),
        inputs={
            "rows": [
                {
                    "number": 10,
                    "label": "b",
                    "frequency": sc.Quantity(1.0, "GHz"),
                },
                {
                    "number": 2,
                    "label": "z",
                    "frequency": sc.Quantity(2.0, "GHz"),
                },
                {
                    "number": 10,
                    "label": "a",
                    "frequency": sc.Quantity(900.0, "MHz"),
                },
                {
                    "number": 10,
                    "label": "a",
                    "frequency": sc.Quantity(2.0, "GHz"),
                },
            ]
        },
        bindings=_input_bindings(rows=rows.value_type),
    )

    assert [row["number"] for row in sorted_rows] == [2, 10, 10, 10]
    assert [row["label"] for row in sorted_rows] == ["z", "a", "a", "b"]
    assert [row["frequency"] for row in sorted_rows[1:3]] == [
        sc.Quantity(900.0, "MHz"),
        sc.Quantity(2.0, "GHz"),
    ]


def test_quantity_equality_and_order_use_a_symmetric_common_base_unit() -> None:
    tiny_ghz = sc.Quantity(1e-13, "GHz")
    tiny_hz = sc.Quantity(1e-4, "Hz")

    assert runtime_values_equal(tiny_ghz, tiny_hz)
    assert runtime_values_equal(tiny_hz, tiny_ghz)
    assert compare_ordered_values(tiny_ghz, tiny_hz) == 0
    assert compare_ordered_values(tiny_hz, tiny_ghz) == 0


def test_typed_sort_rejects_empty_nullable_optional_and_unorderable_columns() -> None:
    rows = sc.input(
        "rows",
        sc.TableType(
            columns=(
                sc.TableColumn("enabled", sc.ScalarType(sc.BoolType())),
                sc.TableColumn(
                    "optional",
                    sc.ScalarType(sc.StringType()),
                    required=False,
                ),
                sc.TableColumn(
                    "nullable",
                    sc.ScalarType(sc.StringType(), nullable=True),
                ),
            )
        ),
    )

    with pytest.raises(ValueError, match="at least one column"):
        rows.sort()
    with pytest.raises(TypeError, match="not orderable"):
        rows.sort("enabled")
    with pytest.raises(TypeError, match="must be required"):
        rows.sort("optional")
    with pytest.raises(TypeError, match="must be non-nullable"):
        rows.sort("nullable")


def test_ordering_requires_finite_numeric_contracts_and_values() -> None:
    open_float = sc.input(
        "value",
        sc.ScalarType(sc.FloatType(finite=False)),
    )
    rows = sc.input(
        "rows",
        sc.TableType(
            columns=(
                sc.TableColumn(
                    "value",
                    sc.ScalarType(sc.FloatType(finite=False)),
                ),
            )
        ),
    )

    with pytest.raises(TypeError, match="guarantee finite"):
        open_float.lt(1.0)
    with pytest.raises(TypeError, match="guarantee finite"):
        rows.sort("value")
    with pytest.raises(ValueError, match="Float bounds must be finite"):
        evaluate_scalar(
            _BACKEND,
            lit(float("nan")).lt(1.0),
            ParameterRelationData().to_context(),
        )


def test_typed_join_requires_explicit_compatible_non_null_keys() -> None:
    left = sc.input(
        "left",
        sc.TableType(
            columns=(
                sc.TableColumn("id", sc.ScalarType(sc.StringType())),
                sc.TableColumn("left_value", sc.ScalarType(sc.IntType())),
            )
        ),
    )
    right = sc.input(
        "right",
        sc.TableType(
            columns=(
                sc.TableColumn("id", sc.ScalarType(sc.StringType())),
                sc.TableColumn("right_value", sc.ScalarType(sc.IntType())),
            )
        ),
    )

    with pytest.raises(ValueError, match="at least one key"):
        left.join(right, on={})

    joined = left.join(right, on={"id": "id"})
    assert isinstance(joined.value_type, sc.TableType)
    assert tuple(column.id for column in joined.value_type.columns) == (
        "id",
        "left_value",
        "right_value",
    )
    assert evaluate_relation(
        _BACKEND,
        internal_lower_table_value_ref(joined),
        inputs={
            "left": [{"id": "q0", "left_value": 1}],
            "right": [{"id": "q0", "right_value": 2}],
        },
        bindings=_input_bindings(
            left=left.value_type,
            right=right.value_type,
        ),
    ) == [{"id": "q0", "left_value": 1, "right_value": 2}]

    incompatible = sc.input(
        "incompatible",
        sc.TableType(columns=(sc.TableColumn("id", sc.ScalarType(sc.IntType())),)),
    )
    nullable = sc.input(
        "nullable",
        sc.TableType(
            columns=(
                sc.TableColumn(
                    "id",
                    sc.ScalarType(sc.StringType(), nullable=True),
                ),
            )
        ),
    )
    with pytest.raises(TypeError, match="not defined"):
        left.join(incompatible, on={"id": "id"})
    with pytest.raises(TypeError, match="required and non-nullable"):
        left.join(nullable, on={"id": "id"})


def test_join_preserves_the_left_typed_representation_of_shared_keys() -> None:
    integer_left = sc.input(
        "integer_left",
        sc.TableType(columns=(sc.TableColumn("id", sc.ScalarType(sc.IntType())),)),
    )
    float_right = sc.input(
        "float_right",
        sc.TableType(columns=(sc.TableColumn("id", sc.ScalarType(sc.FloatType())),)),
    )
    numeric_join = integer_left.join(float_right, on={"id": "id"})

    assert evaluate_relation(
        _BACKEND,
        internal_lower_table_value_ref(numeric_join),
        inputs={"integer_left": [{"id": 1}], "float_right": [{"id": 1.0}]},
        bindings=_input_bindings(
            integer_left=integer_left.value_type,
            float_right=float_right.value_type,
        ),
    ) == [{"id": 1}]

    ghz_left = sc.input(
        "ghz_left",
        sc.TableType(
            columns=(
                sc.TableColumn(
                    "frequency",
                    sc.ScalarType(sc.QuantityType(unit="GHz")),
                ),
            )
        ),
    )
    mhz_right = sc.input(
        "mhz_right",
        sc.TableType(
            columns=(
                sc.TableColumn(
                    "frequency",
                    sc.ScalarType(sc.QuantityType(unit="MHz")),
                ),
            )
        ),
    )
    quantity_join = ghz_left.join(mhz_right, on={"frequency": "frequency"})

    assert evaluate_relation(
        _BACKEND,
        internal_lower_table_value_ref(quantity_join),
        inputs={
            "ghz_left": [{"frequency": sc.Quantity(1.0, "GHz")}],
            "mhz_right": [{"frequency": sc.Quantity(1000.0, "MHz")}],
        },
        bindings=_input_bindings(
            ghz_left=ghz_left.value_type,
            mhz_right=mhz_right.value_type,
        ),
    ) == [{"frequency": sc.Quantity(1.0, "GHz")}]


def test_quantity_join_is_symmetric_even_below_display_unit_rounding() -> None:
    ghz = sc.input(
        "ghz",
        sc.TableType(
            columns=(
                sc.TableColumn(
                    "frequency",
                    sc.ScalarType(sc.QuantityType(unit="GHz")),
                ),
            )
        ),
    )
    hz = sc.input(
        "hz",
        sc.TableType(
            columns=(
                sc.TableColumn(
                    "frequency",
                    sc.ScalarType(sc.QuantityType(unit="Hz")),
                ),
            )
        ),
    )
    tiny_ghz = sc.Quantity(1e-13, "GHz")
    tiny_hz = sc.Quantity(1e-4, "Hz")

    assert evaluate_relation(
        _BACKEND,
        internal_lower_table_value_ref(ghz.join(hz, on={"frequency": "frequency"})),
        inputs={"ghz": [{"frequency": tiny_ghz}], "hz": [{"frequency": tiny_hz}]},
        bindings=_input_bindings(ghz=ghz.value_type, hz=hz.value_type),
    ) == [{"frequency": tiny_ghz}]
    assert evaluate_relation(
        _BACKEND,
        internal_lower_table_value_ref(hz.join(ghz, on={"frequency": "frequency"})),
        inputs={"ghz": [{"frequency": tiny_ghz}], "hz": [{"frequency": tiny_hz}]},
        bindings=_input_bindings(ghz=ghz.value_type, hz=hz.value_type),
    ) == [{"frequency": tiny_hz}]


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
        _BACKEND,
        internal_lower_table_value_ref(partial),
        inputs={"rows": source_rows},
        bindings=_input_bindings(rows=rows.value_type),
    ) == [
        {"group": 1, "value": 10},
        {"group": 1, "value": 20},
    ]
    assert evaluate_relation(
        _BACKEND,
        internal_lower_table_value_ref(overwritten),
        inputs={"rows": source_rows},
        bindings=_input_bindings(rows=rows.value_type),
    ) == [
        {"group": 1, "item": 1, "value": 10},
        {"group": 1, "item": 1, "value": 20},
    ]


def test_dotted_table_columns_are_exact_keys_for_row_access_and_sort() -> None:
    rows = sc.input(
        "rows",
        sc.TableType(
            columns=(
                sc.TableColumn("device.rank", sc.ScalarType(sc.IntType())),
                sc.TableColumn("label", sc.ScalarType(sc.StringType())),
            )
        ),
    )
    transformed = rows.with_columns(
        lambda row: {"copied_rank": row["device.rank"]}
    ).sort("device.rank")

    assert evaluate_relation(
        _BACKEND,
        internal_lower_table_value_ref(transformed),
        inputs={
            "rows": [
                {"device.rank": 2, "label": "second"},
                {"device.rank": 1, "label": "first"},
            ]
        },
        bindings=_input_bindings(rows=rows.value_type),
    ) == [
        {"device.rank": 1, "label": "first", "copied_rank": 1},
        {"device.rank": 2, "label": "second", "copied_rank": 2},
    ]


def test_join_and_cross_reject_non_key_column_collisions() -> None:
    table_type = sc.TableType(
        columns=(
            sc.TableColumn("id", sc.ScalarType(sc.StringType())),
            sc.TableColumn("value", sc.ScalarType(sc.IntType())),
        )
    )
    left = sc.input("left", table_type)
    right = sc.input("right", table_type)

    with pytest.raises(ValueError, match="join has conflicting columns: value"):
        left.join(right, on={"id": "id"})
    with pytest.raises(ValueError, match="cross has conflicting columns"):
        left.cross(right)

    with pytest.raises(ValueError, match="join contains duplicate columns: value"):
        evaluate_relation(
            _BACKEND,
            literal_rows([{"id": "q0", "value": 1}]).join(
                literal_rows([{"id": "q0", "value": 1}]),
                on={"id": "id"},
            ),
        )
    with pytest.raises(ValueError, match="cross contains duplicate columns: id"):
        evaluate_relation(
            _BACKEND,
            literal_rows([{"id": "q0"}]).cross(literal_rows([{"id": "q1"}])),
        )

from __future__ import annotations

import pytest

from scopecat.compiler.relations.verification import (
    PointRequirement,
    RelationPlanVerificationError,
    RelationTypeBindings,
    RowType,
    verify_relation_plan,
)
from scopecat.graph.relations.analysis import PlanNode
from scopecat.graph.relations.model import (
    ParameterLookupUse,
    input_ref,
    input_series,
    input_table,
    lit,
    literal_rows,
    param,
    parameter_lookup,
    parameter_series,
    point_col,
    table,
    values,
)
from scopecat.kernel.value_types import (
    Float,
    Int,
    Quantity,
    Record,
    RecordField,
    Scalar,
    Series,
    String,
    Table,
    TableColumn,
)

INT = Scalar(Int())
FLOAT = Scalar(Float())
STRING = Scalar(String())
FREQUENCY = Scalar(Quantity(dimension="frequency", unit="GHz"))

TABLE_PARAMETER = Table(
    columns=(
        TableColumn("id", STRING),
        TableColumn("gain", FLOAT),
    ),
    primary_key=("id",),
    min_rows=0,
    max_rows=3,
)


def test_context_supplies_null_literal_type_without_losing_nullability() -> None:
    expected = Scalar(Quantity(dimension="frequency", unit="GHz"), nullable=True)

    verified = verify_relation_plan(lit(None), expected_type=expected)

    assert verified.certified_type == expected


@pytest.mark.parametrize(
    ("root", "code"),
    [
        (lit(None), "ambiguous_null"),
        (values([]), "missing_declared_type"),
        (literal_rows([]), "missing_declared_type"),
    ],
)
def test_context_dependent_literals_require_an_expected_type(
    root: PlanNode,
    code: str,
) -> None:
    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(root)

    assert caught.value.code == code
    assert caught.value.path == ()


def test_empty_series_uses_context_for_items() -> None:
    expected = Series(STRING, min_length=0, max_length=10)

    assert verify_relation_plan(values([]), expected_type=expected).certified_type == (
        expected
    )


def test_empty_relation_uses_context_for_schema() -> None:
    expected = Table(
        columns=(TableColumn("frequency", FREQUENCY),),
        min_rows=0,
        max_rows=10,
    )

    assert (
        verify_relation_plan(literal_rows([]), expected_type=expected).certified_type
        == expected
    )


def test_all_null_literal_column_is_typed_from_expected_schema() -> None:
    expected = Table(
        columns=(TableColumn("frequency", Scalar(FREQUENCY.atom, nullable=True)),),
        min_rows=1,
        max_rows=1,
    )

    assert (
        verify_relation_plan(
            literal_rows([{"frequency": None}]),
            expected_type=expected,
        ).certified_type
        == expected
    )


def test_only_referenced_typed_imports_enter_the_proof() -> None:
    bindings = RelationTypeBindings(
        inputs={"used": INT, "unused": FLOAT},
        parameters={"unused": STRING},
    )

    verified = verify_relation_plan(input_ref("used"), bindings=bindings)

    assert [(item.id, item.value_type) for item in verified.imports] == [("used", INT)]


def test_input_and_parameter_namespaces_are_typed_independently() -> None:
    bindings = RelationTypeBindings(
        inputs={"shared": INT},
        parameters={"shared": FLOAT},
    )

    verified = verify_relation_plan(
        input_ref("shared") + param("shared"),
        bindings=bindings,
    )

    assert {(item.namespace.value, item.id) for item in verified.imports} == {
        ("input", "shared"),
        ("parameter", "shared"),
    }


@pytest.mark.parametrize(
    ("root", "bindings"),
    [
        (
            input_ref("wrong"),
            RelationTypeBindings(inputs={"wrong": Series(INT)}),
        ),
        (
            input_series("wrong"),
            RelationTypeBindings(inputs={"wrong": INT}),
        ),
        (
            input_table("wrong"),
            RelationTypeBindings(inputs={"wrong": INT}),
        ),
        (
            param("wrong"),
            RelationTypeBindings(parameters={"wrong": TABLE_PARAMETER}),
        ),
        (
            parameter_series("wrong"),
            RelationTypeBindings(parameters={"wrong": FLOAT}),
        ),
        (
            table("wrong"),
            RelationTypeBindings(parameters={"wrong": FLOAT}),
        ),
    ],
)
def test_typed_imports_reject_reference_shape_mismatches(
    root: PlanNode,
    bindings: RelationTypeBindings,
) -> None:
    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(root, bindings=bindings)

    assert caught.value.code == "import_shape_mismatch"
    assert caught.value.path == ()


def test_unknown_import_reports_a_stable_code() -> None:
    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(input_ref("missing"))

    assert caught.value.code == "unknown_input"
    assert caught.value.path == ()


def test_point_interface_projects_only_referenced_columns() -> None:
    device = Scalar(Record(fields=(RecordField("rank", INT),)))
    point = RowType(
        (
            TableColumn("device", device),
            TableColumn("unused", STRING),
        ),
    )

    verified = verify_relation_plan(
        point_col("device"),
        bindings=RelationTypeBindings(point_row=point),
    )

    assert verified.external_point_requirement == PointRequirement(
        RowType((TableColumn("device", device),)),
        ("device",),
    )


def test_exact_dotted_point_column_takes_precedence_over_record_traversal() -> None:
    point = RowType(
        columns=(
            TableColumn("device.rank", INT),
            TableColumn(
                "device",
                Scalar(Record(fields=(RecordField("rank", STRING),))),
            ),
        )
    )

    verified = verify_relation_plan(
        point_col("device.rank"),
        bindings=RelationTypeBindings(point_row=point),
    )

    assert verified.certified_type == INT


def test_binary_validates_operand_types_before_execution() -> None:
    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(lit("not-a-number") + 1)

    assert caught.value.code == "invalid_scalar_operator"


def test_lookup_use_is_typed_without_importing_the_whole_table() -> None:
    use = ParameterLookupUse(
        table_id="calibration",
        key_input_types=(("device", STRING), ("mode", INT)),
        literal_key_columns=frozenset({"device", "mode"}),
        column_id="gain",
        result_type=FLOAT,
    )

    verified = verify_relation_plan(
        parameter_lookup(use, key={"mode": 1, "device": "q0"})
    )

    assert verified.certified_type == FLOAT
    assert verified.imports[0].lookup == use
    assert verified.imports[0].value_type == FLOAT


def test_lookup_occurrences_own_distinct_literal_key_input_types() -> None:
    uses = (
        ParameterLookupUse(
            table_id="calibration",
            key_input_types=(("device", Scalar(String(min_length=2, max_length=2))),),
            literal_key_columns=frozenset({"device"}),
            column_id="gain",
            result_type=FLOAT,
        ),
        ParameterLookupUse(
            table_id="calibration",
            key_input_types=(("device", Scalar(String(min_length=9, max_length=9))),),
            literal_key_columns=frozenset({"device"}),
            column_id="gain",
            result_type=FLOAT,
        ),
    )

    verified = verify_relation_plan(
        parameter_lookup(uses[0], key={"device": "q0"})
        + parameter_lookup(uses[1], key={"device": "long-name"}),
    )

    assert {imported.lookup for imported in verified.imports} == set(uses)


def test_lookup_use_preserves_key_expression_errors() -> None:
    use = ParameterLookupUse(
        table_id="calibration",
        key_input_types=(("device", STRING),),
        literal_key_columns=frozenset(),
        column_id="gain",
        result_type=FLOAT,
    )

    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(
            parameter_lookup(use, key={"device": input_ref("missing")}),
        )

    assert caught.value.code == "unknown_input"
    assert caught.value.path == ("key", "device")


def test_lookup_expression_requires_exactly_its_declared_key_inputs() -> None:
    use = ParameterLookupUse(
        table_id="calibration",
        key_input_types=(("device", STRING),),
        literal_key_columns=frozenset(),
        column_id="gain",
        result_type=FLOAT,
    )

    with pytest.raises(ValueError, match="exactly match"):
        parameter_lookup(
            use,
            key={"device": "q0", "mode": 1},
        )


def test_verified_plan_retains_the_internal_relation_ast() -> None:
    source = literal_rows([{"value": 1}])
    expected = Table(columns=(TableColumn("value", INT),))
    verified = verify_relation_plan(source, expected_type=expected)

    assert verified.root is source

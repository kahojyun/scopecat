from __future__ import annotations

import pytest

from scopecat.compiler.relations.verification import (
    PointRequirement,
    RelationPlanVerificationError,
    RelationTypeBindings,
    RowType,
    verify_relation_plan,
)
from scopecat.graph.relations.model import (
    ParameterLookupUse,
    input_ref,
    lit,
    param,
    parameter_lookup,
    point_col,
)
from scopecat.kernel.value_types import (
    Float,
    Int,
    Scalar,
    String,
    TableColumn,
)

INT = Scalar(Int())
FLOAT = Scalar(Float())
STRING = Scalar(String())


def test_null_literal_requires_an_expected_type() -> None:
    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(lit(None))

    assert caught.value.code == "unsupported_null"
    assert caught.value.path == ()


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


def test_unknown_import_reports_a_stable_code() -> None:
    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(input_ref("missing"))

    assert caught.value.code == "unknown_input"
    assert caught.value.path == ()


def test_point_interface_projects_only_referenced_columns() -> None:
    device = INT
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


def test_exact_dotted_point_column_is_selected() -> None:
    point = RowType(
        columns=(
            TableColumn("device.rank", INT),
            TableColumn("device", STRING),
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


def test_verified_plan_retains_the_scalar_ast() -> None:
    source = lit(1)
    verified = verify_relation_plan(source, expected_type=INT)

    assert verified.root is source

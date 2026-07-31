from __future__ import annotations

import pytest

from scopecat.compiler.relations.verification import (
    PointRequirement,
    RelationPlanVerificationError,
    RelationTypeBindings,
    RowType,
    relation_plan_imports,
    relation_plan_point_requirement,
    verify_relation_plan,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import (
    Entity,
    Float,
    Int,
    Quantity,
    Scalar,
    String,
    TableColumn,
)
from scopecat.program.expressions import (
    ComputeResultScalarExpr,
    ModuleExportScalarExpr,
    ParameterLookupUse,
    input_ref,
    lit,
    param,
    parameter_lookup,
    point_col,
)
from scopecat.program.identities import InvocationKey
from scopecat.program.value_graph import ValueId

INT = Scalar(Int())
FLOAT = Scalar(Float())
STRING = Scalar(String())
QUANTITY = Scalar(Quantity())
BOUNDED_FREQUENCY = Scalar(Quantity(unit="GHz", minimum=4.0, maximum=6.0))


def test_typed_null_literal_is_rejected() -> None:
    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(lit(None, INT))

    assert caught.value.code == "invalid_literal"
    assert caught.value.path == ()


def test_literal_carries_its_contextual_scalar_type() -> None:
    entity_type = Scalar(Entity())
    source = lit("q0", entity_type)

    verified = verify_relation_plan(source, expected_type=entity_type)

    assert verified is source
    assert verified.value_type == entity_type


def test_only_referenced_typed_imports_enter_the_proof() -> None:
    bindings = RelationTypeBindings(
        inputs={"used": INT, "unused": FLOAT},
        parameters={"unused": STRING},
    )

    verified = verify_relation_plan(input_ref("used", INT), bindings=bindings)

    assert [(item.id, item.value_type) for item in relation_plan_imports(verified)] == [
        ("used", INT)
    ]


def test_input_and_parameter_namespaces_are_typed_independently() -> None:
    bindings = RelationTypeBindings(
        inputs={"shared": INT},
        parameters={"shared": FLOAT},
    )

    verified = verify_relation_plan(
        input_ref("shared", INT) + param("shared", FLOAT),
        bindings=bindings,
    )

    assert {
        (item.namespace.value, item.id) for item in relation_plan_imports(verified)
    } == {
        ("input", "shared"),
        ("parameter", "shared"),
    }


def test_unknown_import_reports_a_stable_code() -> None:
    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(input_ref("missing", INT))

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
        point_col("device", device),
        bindings=RelationTypeBindings(point_row=point),
    )

    assert relation_plan_point_requirement(verified) == PointRequirement(
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
        point_col("device.rank", INT),
        bindings=RelationTypeBindings(point_row=point),
    )

    assert verified.value_type == INT


def test_binding_must_be_assignable_to_the_expression_intrinsic_type() -> None:
    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(
            input_ref("value", FLOAT),
            bindings=RelationTypeBindings(inputs={"value": INT}),
        )

    assert caught.value.code == "intrinsic_type_mismatch"
    assert caught.value.path == ()


def test_narrow_binding_satisfies_a_generic_intrinsic_and_expected_type() -> None:
    source = param("frequency", QUANTITY)

    verified = verify_relation_plan(
        source,
        bindings=RelationTypeBindings(parameters={"frequency": BOUNDED_FREQUENCY}),
        expected_type=BOUNDED_FREQUENCY,
    )

    assert verified is source
    assert verified.value_type == QUANTITY


def test_binary_validates_operand_types_during_construction() -> None:
    with pytest.raises(TypeError, match="operator '\\+' is not defined"):
        _invalid = lit("not-a-number") + 1


def test_binary_intrinsic_type_is_cross_checked_during_verification() -> None:
    expression = lit(1) + 1
    object.__setattr__(expression, "value_type", FLOAT)

    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(expression)

    assert caught.value.code == "intrinsic_type_mismatch"


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

    assert verified.value_type == FLOAT
    imports = relation_plan_imports(verified)
    assert imports[0].lookup == use
    assert imports[0].value_type == FLOAT


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
            parameter_lookup(use, key={"device": input_ref("missing", STRING)}),
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

    assert verified is source


@pytest.mark.parametrize(
    ("expression", "code"),
    [
        (
            ComputeResultScalarExpr(
                value_id=ValueId(SymbolId(local_id="result")),
                value_type=INT,
            ),
            "compute_result_unavailable",
        ),
        (
            ModuleExportScalarExpr(
                invocation_key=InvocationKey.fresh(),
                export_id="result",
                value_type=INT,
            ),
            "unresolved_module_export",
        ),
    ],
)
def test_pure_relation_plan_rejects_opaque_expression_edges(
    expression: ComputeResultScalarExpr | ModuleExportScalarExpr,
    code: str,
) -> None:
    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(expression)

    assert caught.value.code == code

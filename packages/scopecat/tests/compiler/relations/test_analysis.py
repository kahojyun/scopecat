from scopecat.kernel.value_types import (
    Float,
    Scalar,
    String,
)
from scopecat.program.expression_analysis import plan_input_refs
from scopecat.program.expressions import (
    ParameterLookupUse,
    input_ref,
    param,
    parameter_lookup,
    point_col,
)

_FLOAT = Scalar(Float())
_STRING = Scalar(String())


def test_plan_input_refs_deduplicates_scalar_references() -> None:
    repeated = input_ref("shared", _FLOAT) + input_ref("shared", _FLOAT)

    assert plan_input_refs(repeated) == ("shared",)


def test_plan_input_refs_cover_nested_lookup_keys() -> None:
    lookup = parameter_lookup(
        ParameterLookupUse(
            table_id="calibrations",
            key_input_types=(
                ("device", _STRING),
                ("point", _STRING),
            ),
            literal_key_columns=frozenset(),
            column_id="gain",
            result_type=_FLOAT,
        ),
        key={
            "device": input_ref("device", _STRING),
            "point": point_col("point_id", _STRING),
        },
    )
    plan = input_ref("start", _FLOAT) + lookup + param("stop", _FLOAT)

    assert plan_input_refs(plan) == ("device", "start")

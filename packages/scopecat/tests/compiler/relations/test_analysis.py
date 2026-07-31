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


def test_plan_input_refs_deduplicates_scalar_references() -> None:
    repeated = input_ref("shared") + input_ref("shared")

    assert plan_input_refs(repeated) == ("shared",)


def test_plan_input_refs_cover_nested_lookup_keys() -> None:
    lookup = parameter_lookup(
        ParameterLookupUse(
            table_id="calibrations",
            key_input_types=(
                ("device", Scalar(String())),
                ("point", Scalar(String())),
            ),
            literal_key_columns=frozenset(),
            column_id="gain",
            result_type=_FLOAT,
        ),
        key={
            "device": input_ref("device"),
            "point": point_col("point_id"),
        },
    )
    plan = input_ref("start") + lookup + param("stop")

    assert plan_input_refs(plan) == ("device", "start")

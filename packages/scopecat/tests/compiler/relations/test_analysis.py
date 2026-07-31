from scopecat.kernel.value_types import (
    Float,
    Scalar,
    String,
)
from scopecat.program.expression_analysis import expression_input_refs
from scopecat.program.expressions import (
    ParameterLookupUse,
    input_ref,
    param,
    parameter_lookup,
    point_col,
)

_FLOAT = Scalar(Float())
_STRING = Scalar(String())


def test_expression_input_refs_deduplicate_scalar_references() -> None:
    repeated = input_ref("shared", _FLOAT) + input_ref("shared", _FLOAT)

    assert expression_input_refs(repeated) == ("shared",)


def test_expression_input_refs_cover_nested_lookup_keys() -> None:
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
    expression = input_ref("start", _FLOAT) + lookup + param("stop", _FLOAT)

    assert expression_input_refs(expression) == ("device", "start")

import pytest

from scopecat._compiler.program import ComputeNodeInput, ComputeNodeSpec
from scopecat._planning.compute_dependencies import (
    summarize_compute_node_dependencies,
)
from scopecat._relations import (
    ParameterRelationData,
    input_ref,
    param,
    parameter_series,
    table,
)
from scopecat._runtime.compute import (  # pyright: ignore[reportPrivateUsage]
    _versioned_value,
)
from scopecat._value_expressions import as_value_expr
from scopecat.models.entity import EntityRef
from scopecat.value_types import Bool, Float, Scalar, Series, Table


def test_bound_value_is_dependency_authority_for_all_parameter_shapes() -> None:
    node = ComputeNodeSpec(
        id="consume-parameters",
        inputs={
            "gain": ComputeNodeInput(
                kind="value",
                value=as_value_expr(param("gain")),
                source_inputs=["gain_input"],
                value_type=Scalar(Float()),
            ),
            "offsets": ComputeNodeInput(
                kind="value",
                value=as_value_expr(parameter_series("offsets")),
                source_inputs=["offsets_input"],
                value_type=Series(Scalar(Float())),
            ),
            "calibrations": ComputeNodeInput(
                kind="value",
                value=as_value_expr(table("calibrations")),
                source_inputs=["calibrations_input"],
                value_type=Table(columns=(), allow_extra_columns=True),
            ),
            "runtime_value": ComputeNodeInput(
                kind="value",
                value=as_value_expr(input_ref("runtime_value")),
                source_inputs=["runtime_value"],
                value_type=Scalar(Float()),
            ),
        },
        output_type=Scalar(Bool()),
    )

    dependencies = summarize_compute_node_dependencies(node)

    assert dependencies.parameters == ("calibrations", "gain", "offsets")
    assert dependencies.input_refs == ("runtime_value",)


def test_entity_cache_fingerprint_uses_identity_not_metadata() -> None:
    configured = EntityRef(
        id="q0",
        kind="logical_qubit",
        metadata={"label": "configured"},
    )
    observed = EntityRef(
        id="q0",
        kind="logical_qubit",
        metadata={"label": "observed"},
    )

    assert _versioned_value(configured) == _versioned_value(observed)
    assert _versioned_value(configured) != _versioned_value(
        EntityRef(id="q0", kind="physical_qubit")
    )
    assert _versioned_value(configured) != _versioned_value(
        EntityRef(id="q1", kind="logical_qubit")
    )


def test_parameter_relation_data_rejects_cross_shape_id_collisions() -> None:
    with pytest.raises(ValueError, match="parameter ids must be unique"):
        ParameterRelationData(
            scalars={"shared": 1},
            series={"shared": [2]},
            tables={"shared": [{"value": 3}]},
        )

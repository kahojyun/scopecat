from dataclasses import replace

import pytest

from scopecat._compiler.binding import bind_program
from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.ids import NodeId
from scopecat._compiler.program import (
    TypedComputeNode,
    TypedPointSource,
    ValueInput,
    typed_program,
)
from scopecat._execution.engine import (  # pyright: ignore[reportPrivateUsage]
    _versioned_value,
)
from scopecat._relations import (
    ParameterRelationData,
    lit,
    literal_rows,
    param,
    parameter_series,
    table,
)
from scopecat._value_expressions import as_value_expr
from scopecat.models.entity import EntityRef
from scopecat.value_types import Bool, Float, Scalar, Series, Table
from tests.support.authoring import load_config


def test_bound_compute_call_carries_dependency_provenance() -> None:
    node = TypedComputeNode(
        id=NodeId(local_id="consume-parameters"),
        inputs={
            "gain": ValueInput(
                value=as_value_expr(param("gain")),
                source_inputs=("gain_input",),
                value_type=Scalar(Float()),
            ),
            "offsets": ValueInput(
                value=as_value_expr(parameter_series("offsets")),
                source_inputs=("offsets_input",),
                value_type=Series(Scalar(Float())),
            ),
            "calibrations": ValueInput(
                value=as_value_expr(table("calibrations")),
                source_inputs=("calibrations_input",),
                value_type=Table(columns=(), allow_extra_columns=True),
            ),
            "runtime_value": ValueInput(
                value=as_value_expr(lit(1.0)),
                source_inputs=("runtime_value",),
                value_type=Scalar(Float()),
            ),
        },
        output_type=Scalar(Bool()),
        fn=lambda **_inputs: True,
    )
    program = typed_program(
        id="dependency-provenance",
        kind="compiler_test",
        point_source=TypedPointSource(
            expr=literal_rows([{}]),
            value_type=Table(columns=(), min_rows=1, max_rows=1),
        ),
        compute_nodes=(node,),
    )
    parameters = ParameterRelationData(
        scalars={"gain": 1.0},
        series={"offsets": [1.0, 2.0]},
        tables={"calibrations": [{"gain": 1.0}]},
    )
    environment = replace(
        validate_config_environment(load_config()),
        parameters=parameters,
    )

    plan = bind_program(program, environment)

    assert plan.points[0].compute[0].dependencies == {
        "input_refs": (
            "calibrations_input",
            "gain_input",
            "offsets_input",
            "runtime_value",
        ),
        "parameters": ("calibrations", "gain", "offsets"),
    }


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

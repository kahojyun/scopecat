from dataclasses import replace

import pytest

from scopecat._compiler.binding import bind_program
from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.point_domain import PointDomain
from scopecat._compiler.program import (
    TypedComputeNode,
    TypedComputeOutput,
    ValueInput,
    typed_program,
)
from scopecat._execution.engine import (  # pyright: ignore[reportPrivateUsage]
    _versioned_value,
)
from scopecat._operation_contract import LOCAL_OPAQUE_OPERATION_CONTRACT
from scopecat._point_domain_algebra import POINT_UNIT
from scopecat._relation_backend import ParameterRelationData
from scopecat._relation_verification import RelationTypeBindings
from scopecat._relations import lit, param, parameter_series, table
from scopecat._semantic_graph import (
    ImplementationCatalog,
    ImplementationId,
    LocalPythonImplementation,
    OperationId,
    operation_result_id,
)
from scopecat._symbols import SymbolId
from scopecat._value_availability import ValueAvailability, ValueRate, ValueStage
from scopecat.models.entity import EntityRef
from scopecat.value_types import Bool, Float, Scalar, Series, Table
from tests.support.authoring import load_config
from tests.support.relation_plans import value_expr


def test_bound_compute_call_carries_dependency_provenance() -> None:
    operation_id = OperationId(SymbolId(local_id="consume-parameters"))
    gain_type = Scalar(Float())
    offsets_type = Series(Scalar(Float()))
    calibrations_type = Table(columns=(), allow_extra_columns=True)
    bindings = RelationTypeBindings(
        parameters={
            "gain": gain_type,
            "offsets": offsets_type,
            "calibrations": calibrations_type,
        }
    )
    node = TypedComputeNode(
        id=operation_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        inputs={
            "gain": ValueInput(
                value=value_expr(
                    param("gain"),
                    expected_type=gain_type,
                    bindings=bindings,
                ),
                origin_input_ids=("gain_input",),
            ),
            "offsets": ValueInput(
                value=value_expr(
                    parameter_series("offsets"),
                    expected_type=offsets_type,
                    bindings=bindings,
                ),
                origin_input_ids=("offsets_input",),
            ),
            "calibrations": ValueInput(
                value=value_expr(
                    table("calibrations"),
                    expected_type=calibrations_type,
                    bindings=bindings,
                ),
                origin_input_ids=("calibrations_input",),
            ),
            "runtime_value": ValueInput(
                value=value_expr(lit(1.0), expected_type=gain_type),
                origin_input_ids=("runtime_value",),
            ),
        },
        result=TypedComputeOutput(
            id=operation_result_id(operation_id),
            value_type=Scalar(Bool()),
            availability=ValueAvailability(ValueStage.EXECUTE, ValueRate.POINT),
        ),
    )
    program = typed_program(
        id="dependency-provenance",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        compute_nodes=(node,),
        implementation_catalog=ImplementationCatalog(
            local_python=(
                LocalPythonImplementation(
                    id=ImplementationId("python.consume-parameters.v1"),
                    operation_id=operation_id,
                    operation_contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                    kernel=lambda **_inputs: True,
                ),
            )
        ),
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

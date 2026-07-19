from dataclasses import replace

import pytest

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.relations.evaluation import ParameterRelationData
from scopecat.compiler.relations.model import (
    lit,
    param,
    parameter_series,
    table,
)
from scopecat.compiler.relations.point_domain import POINT_UNIT
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.availability import (
    ValueAvailability,
    ValueRate,
    ValueStage,
)
from scopecat.compiler.semantic.model import (
    ImplementationCatalog,
    ImplementationId,
    LocalPythonImplementation,
    OperationId,
    operation_result_id,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    TypedComputeNode,
    TypedComputeOutput,
    ValueInput,
)
from scopecat.execution.effect_interpreter import (
    versioned_value,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Bool, Float, Scalar, Series, Table
from scopecat.planning.local_materialization import materialize_local_execution
from scopecat.records.entity import EntityRef
from tests.testkit.authoring import load_config
from tests.testkit.relation_plans import value_expr
from tests.testkit.typed_program import link_program, typed_program


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
                    kernel=_true_kernel,
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

    plan = materialize_local_execution(link_program(program, environment))

    assert plan.points[0].compute_operations[0].dependencies == {
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

    assert versioned_value(configured) == versioned_value(observed)
    assert versioned_value(configured) != versioned_value(
        EntityRef(id="q0", kind="physical_qubit")
    )
    assert versioned_value(configured) != versioned_value(
        EntityRef(id="q1", kind="logical_qubit")
    )


def test_parameter_relation_data_rejects_cross_shape_id_collisions() -> None:
    with pytest.raises(ValueError, match="parameter ids must be unique"):
        ParameterRelationData(
            scalars={"shared": 1},
            series={"shared": [2]},
            tables={"shared": [{"value": 3}]},
        )


def _true_kernel(**_inputs: object) -> bool:
    return True

from dataclasses import replace

import pytest

from scopecat.compiler.relations.context import ParameterRelationData
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.model import (
    ImplementationId,
    LocalPythonImplementation,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    TypedComputeNode,
    ValueInput,
)
from scopecat.config.environment import build_config_environment
from scopecat.graph.relations.model import (
    lit,
    param,
    parameter_series,
    table,
)
from scopecat.graph.relations.point_domain import POINT_UNIT
from scopecat.graph.values import (
    ComputeOutput,
    OperationId,
    operation_result_id,
)
from scopecat.kernel.content_identity import content_fingerprint
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Bool, Float, Scalar, Series, Table
from tests.testkit.authoring import load_config
from tests.testkit.local_materialization import materialize_local_execution
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
        implementation=LocalPythonImplementation(
            id=ImplementationId("python.consume-parameters.v1"),
            kernel=_true_kernel,
        ),
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
        result=ComputeOutput(
            id=operation_result_id(operation_id),
            value_type=Scalar(Bool()),
        ),
    )
    program = typed_program(
        id="dependency-provenance",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        compute_nodes=(node,),
    )
    parameters = ParameterRelationData(
        scalars={"gain": 1.0},
        series={"offsets": [1.0, 2.0]},
        tables={"calibrations": [{"gain": 1.0}]},
    )
    environment = replace(
        build_config_environment(load_config()),
        parameters=parameters,
    )

    plan = materialize_local_execution(link_program(program, environment))

    assert plan.preamble_operations[0].dependencies == {
        "input_refs": (
            "calibrations_input",
            "gain_input",
            "offsets_input",
            "runtime_value",
        ),
        "parameters": ("calibrations", "gain", "offsets"),
    }


def test_entity_content_fingerprint_uses_identity_not_metadata() -> None:
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

    assert content_fingerprint(configured) == content_fingerprint(observed)
    assert content_fingerprint(configured) != content_fingerprint(
        EntityRef(id="q0", kind="physical_qubit")
    )
    assert content_fingerprint(configured) != content_fingerprint(
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

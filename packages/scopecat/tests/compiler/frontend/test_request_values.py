from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.compiler.frontend.request_values import project_run_request_inputs
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.symbols import SymbolId
from scopecat.program.expressions import ComputeResultScalarExpr, input_ref
from scopecat.program.value_graph import OperationId, operation_result_id
from scopecat.program.values import input as program_input


def test_request_projection_handles_authoring_semantic_values() -> None:
    projected = project_run_request_inputs(
        {
            "subjects": (
                EntityRef(id="q0", kind="qubit"),
                EntityRef(id="q1", kind="qubit"),
            )
        }
    )

    assert projected == {
        "subjects": [
            {
                "kind": "entity",
                "entity_id": "q0",
                "entity_kind": "qubit",
                "metadata": {},
            },
            {
                "kind": "entity",
                "entity_id": "q1",
                "entity_kind": "qubit",
                "metadata": {},
            },
        ]
    }


def test_request_projection_rejects_transient_graph_values() -> None:
    entity_type = sc.ScalarType(sc.EntityType())
    transient_values = (
        program_input("subject", entity_type),
        input_ref("subject", entity_type),
        ComputeResultScalarExpr(
            value_id=operation_result_id(
                OperationId(SymbolId(local_id="build-program"))
            ),
            value_type=entity_type,
        ),
    )

    for value in transient_values:
        with pytest.raises(ValueError, match="unsupported authoring run request value"):
            project_run_request_inputs({"value": value})
        with pytest.raises(ValueError, match="unsupported authoring run request value"):
            project_run_request_inputs({"nested": {"value": value}})

from __future__ import annotations

import pytest

from scopecat._compiler.ids import NodeId
from scopecat._compiler.program import (
    ResourceRouteIntent,
    RouteInput,
    TypedComputeNode,
    TypedPointSource,
    TypedProgram,
    observable,
    set_state_field,
)
from scopecat._compiler.verification import verify_typed_program
from scopecat._compute_result import ComputeResultRef
from scopecat._relations import literal_rows
from scopecat.errors import CheckFailed
from scopecat.value_types import Float, Route, Scalar, Table


def _program(**updates: object) -> TypedProgram:
    program = TypedProgram(
        id="verification",
        kind="test",
        point_source=TypedPointSource(
            expr=literal_rows([{}]),
            value_type=Table(columns=(), min_rows=1, max_rows=1),
        ),
    )
    return program.model_copy(update=updates)


def test_typed_program_verifier_rejects_incomplete_compute_route() -> None:
    node = TypedComputeNode(
        id=NodeId(local_id="consume-route"),
        inputs={
            "route": RouteInput(
                port_id="drive",
                value_type=Route(capabilities=("set_gain",)),
            )
        },
        output_type=Scalar(Float()),
    )
    program = _program(
        compute_nodes=(node,),
        route_intents=(
            ResourceRouteIntent(
                port_id="drive",
                capabilities=("set_frequency",),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as error:
        verify_typed_program(program)

    assert error.value.problems[0].code == ("compute_route_capability_missing")


def test_typed_program_verifier_rejects_non_payload_state_compute() -> None:
    node_id = NodeId(local_id="numeric")
    program = _program(
        compute_nodes=(
            TypedComputeNode(
                id=node_id,
                output_type=Scalar(Float()),
            ),
        ),
        state=(
            set_state_field(
                "drive",
                capability_id="set_gain",
                field_path="value",
                value=ComputeResultRef(node_id=node_id),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as error:
        verify_typed_program(program)

    assert error.value.problems[0].code == "compute_payload_unavailable"


def test_typed_program_verifier_checks_static_record_schema() -> None:
    program = _program(
        records=(observable("signal", unit="not-a-unit"),),
    )

    with pytest.raises(CheckFailed) as error:
        verify_typed_program(program)

    assert error.value.problems[0].code == "experiment_record_unit_unsupported"

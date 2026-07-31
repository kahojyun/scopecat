"""Lower typed pure computation into executable local compute operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.typed.values import CompilerValue
from scopecat.execution.local.program import (
    BoundInput,
    ComputeOperation,
    OutputInput,
    PayloadSlot,
)
from scopecat.kernel.payloads import unwrap_payload_values
from scopecat.kernel.problems import Problem, model_location
from scopecat.kernel.value_types import Payload, Scalar
from scopecat.kernel.value_validation import coerce_literal
from scopecat.planning.local_values import evaluate_scalar_value
from scopecat.program.expressions import ComputeResultScalarExpr, ScalarExpr
from scopecat.program.logical import LocalPythonImplementation, LogicalComputeNode
from scopecat.program.value_graph import ComputeOutput, OperationId, ValueId


def bind_compute_operations(
    nodes: Sequence[LogicalComputeNode],
    implementations: Mapping[OperationId, LocalPythonImplementation],
    values: Mapping[ValueId, CompilerValue],
    *,
    operation_prefix: str,
    ctx: EvalContext,
    demanded_payload_results: AbstractSet[ValueId],
    problems: list[Problem],
) -> tuple[
    tuple[ComputeOperation, ...],
    dict[ValueId, str],
]:
    operations: list[ComputeOperation] = []
    payload_ids: dict[ValueId, str] = {}
    available_results: set[ValueId] = set()
    for node in nodes:
        inputs: dict[str, BoundInput | OutputInput] = {}
        failed = False
        input_types = dict(node.input_types)
        for name, value_id in node.inputs:
            input_spec = values[value_id]
            if not isinstance(input_spec, ScalarExpr):
                raise AssertionError("compute inputs must be scalar")
            expected_type = input_types[name]
            try:
                if isinstance(input_spec, ComputeResultScalarExpr):
                    if input_spec.value_id not in available_results:
                        msg = (
                            f"compute result "
                            f"{input_spec.value_id.qualified_name!r} is not available"
                        )
                        raise ValueError(msg)
                    inputs[name] = OutputInput(
                        value_id=input_spec.value_id,
                        value_type=expected_type,
                    )
                else:
                    value = unwrap_payload_values(
                        coerce_literal(
                            expected_type,
                            evaluate_scalar_value(
                                input_spec,
                                ctx,
                                expected_type=expected_type,
                            ),
                            path=("compute", *node.id.scope, node.id.local_id, name),
                        )
                    )
                    inputs[name] = BoundInput(value)
            except (ArithmeticError, KeyError, TypeError, ValueError) as error:
                failed = True
                problems.append(
                    compiler_problem(
                        "compute_node_input_binding_failed",
                        f"compute node {node.id} input {name!r} failed: {error}",
                        model_location(
                            "compute",
                            *node.id.scope,
                            node.id.local_id,
                            name,
                        ),
                    )
                )
        if failed:
            continue
        implementation = implementations[node.id]
        operation_id = f"{operation_prefix}.compute.{node.id.qualified_name}"
        schema_id = (
            _payload_schema(node.result_type)
            if node.result_id in demanded_payload_results
            else None
        )
        payload_id = f"{operation_id}.payload" if schema_id is not None else None
        if payload_id is not None:
            payload_ids[node.result_id] = payload_id
        operations.append(
            ComputeOperation(
                operation_id=operation_id,
                logical_compute_node_id=node.id.qualified_name,
                implementation_id=implementation.id.value,
                kernel=implementation.kernel,
                inputs=inputs,
                result=ComputeOutput(
                    id=node.result_id,
                    value_type=node.result_type,
                ),
                payload_slot=(
                    PayloadSlot(id=payload_id, schema_id=schema_id)
                    if payload_id is not None and schema_id is not None
                    else None
                ),
            )
        )
        available_results.add(node.result_id)
    return tuple(operations), payload_ids


def _payload_schema(value_type: object) -> str | None:
    if isinstance(value_type, Scalar) and isinstance(value_type.atom, Payload):
        return value_type.atom.schema_id
    return None

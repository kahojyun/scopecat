"""Lower typed pure computation into executable local compute operations."""

from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Set as AbstractSet

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.typed.program import TypedComputeNode, ValueInput
from scopecat.execution.local.program import (
    BoundInput,
    ComputeOperation,
    OutputInput,
    PayloadSlot,
)
from scopecat.graph.values import ValueId
from scopecat.kernel.payloads import unwrap_payload_values
from scopecat.kernel.problems import Problem, model_location
from scopecat.kernel.value_types import Payload, Scalar
from scopecat.kernel.value_validation import coerce_literal
from scopecat.planning.local_values import evaluate_value_expr


def bind_compute_operations(
    nodes: Sequence[TypedComputeNode],
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
        for name, input_spec in node.inputs.items():
            try:
                if isinstance(input_spec, ValueInput):
                    value = unwrap_payload_values(
                        coerce_literal(
                            input_spec.value_type,
                            evaluate_value_expr(
                                input_spec.value,
                                input_spec.value.plan,
                                ctx,
                            ),
                            path=("compute", *node.id.scope, node.id.local_id, name),
                        )
                    )
                    inputs[name] = BoundInput(value)
                else:
                    if input_spec.value_id not in available_results:
                        msg = (
                            f"compute result "
                            f"{input_spec.value_id.qualified_name!r} is not available"
                        )
                        raise ValueError(msg)
                    inputs[name] = OutputInput(input_spec.value_id)
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
        implementation = node.implementation
        operation_id = f"{operation_prefix}.compute.{node.id.qualified_name}"
        schema_id = (
            _payload_schema(node.result.value_type)
            if node.result.id in demanded_payload_results
            else None
        )
        payload_id = f"{operation_id}.payload" if schema_id is not None else None
        if payload_id is not None:
            payload_ids[node.result.id] = payload_id
        operations.append(
            ComputeOperation(
                operation_id=operation_id,
                semantic_operation_id=node.id.qualified_name,
                implementation_id=implementation.id.value,
                kernel=implementation.kernel,
                inputs=inputs,
                result=node.result,
                payload_slot=(
                    PayloadSlot(id=payload_id, schema_id=schema_id)
                    if payload_id is not None and schema_id is not None
                    else None
                ),
            )
        )
        available_results.add(node.result.id)
    return tuple(operations), payload_ids


def _payload_schema(value_type: object) -> str | None:
    if isinstance(value_type, Scalar) and isinstance(value_type.atom, Payload):
        return value_type.atom.schema_id
    return None

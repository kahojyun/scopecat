"""Lower typed pure computation into executable local compute operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.relations.evaluation import EvalContext
from scopecat.compiler.semantic.model import ValueId
from scopecat.compiler.typed.dependencies import ComputePlan
from scopecat.compiler.typed.program import TypedComputeNode, ValueInput
from scopecat.compiler.typed.verification import VerifiedCoreProgram
from scopecat.execution.local.program import (
    BoundInput,
    ComputeOperation,
    OutputInput,
    PayloadSlot,
)
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
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
    compute_plan: ComputePlan,
    demanded_payload_results: set[ValueId],
    problems: list[Problem],
    verified_program: VerifiedCoreProgram,
    initial_signatures: Mapping[ValueId, str] | None = None,
) -> tuple[
    tuple[ComputeOperation, ...],
    dict[ValueId, str],
    dict[ValueId, str],
]:
    operations: list[ComputeOperation] = []
    signatures = dict(initial_signatures or {})
    payload_ids: dict[ValueId, str] = {}
    for node in nodes:
        inputs: dict[str, BoundInput | OutputInput] = {}
        signature_inputs: dict[str, object] = {}
        failed = False
        for name, input_spec in node.inputs.items():
            try:
                if isinstance(input_spec, ValueInput):
                    value = unwrap_payload_values(
                        coerce_literal(
                            input_spec.value_type,
                            evaluate_value_expr(
                                input_spec.value,
                                verified_program.relation_plan(
                                    input_spec.relation_use_id
                                ),
                                ctx,
                            ),
                            path=("compute", *node.id.scope, node.id.local_id, name),
                        )
                    )
                    inputs[name] = BoundInput(value)
                    signature_inputs[name] = content_fingerprint(value)
                else:
                    owner = compute_plan.output_owners.get(input_spec.value_id)
                    if owner is None:
                        msg = (
                            "compute result "
                            f"{input_spec.value_id.qualified_name!r} has no owner"
                        )
                        raise ValueError(msg)
                    upstream_signature = signatures.get(input_spec.value_id)
                    if upstream_signature is None:
                        msg = (
                            f"producer {owner.qualified_name!r} result "
                            f"{input_spec.value_id.qualified_name!r} is not available"
                        )
                        raise ValueError(msg)
                    inputs[name] = OutputInput(input_spec.value_id)
                    signature_inputs[name] = {"compute": upstream_signature}
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
        signature = stable_content_hash(
            {
                "operation": node.id.qualified_name,
                "contract": content_fingerprint(node.contract),
                "interface": content_fingerprint(
                    (
                        tuple(
                            sorted(
                                (name, value.value_type)
                                for name, value in node.inputs.items()
                            )
                        ),
                        node.result.value_type,
                    )
                ),
                "implementation": implementation.id.value,
                "inputs": signature_inputs,
            }
        )
        signatures[node.result.id] = signature
        schema_id = (
            _payload_schema(node.result.value_type)
            if node.result.id in demanded_payload_results
            else None
        )
        payload_id = (
            f"{node.result.id.qualified_name}.payload.{signature}"
            if schema_id is not None
            else None
        )
        if payload_id is not None:
            payload_ids[node.result.id] = payload_id
        operations.append(
            ComputeOperation(
                operation_id=(f"{operation_prefix}.compute.{node.id.qualified_name}"),
                semantic_operation_id=node.id.qualified_name,
                implementation_id=implementation.id.value,
                kernel=implementation.kernel,
                inputs=inputs,
                result=node.result,
                dependencies=dict(compute_plan.dependencies[node.id].as_mapping()),
                payload_slot=(
                    PayloadSlot(id=payload_id, schema_id=schema_id)
                    if payload_id is not None and schema_id is not None
                    else None
                ),
            )
        )
    return tuple(operations), payload_ids, signatures


def _payload_schema(value_type: object) -> str | None:
    if isinstance(value_type, Scalar) and isinstance(value_type.atom, Payload):
        return value_type.atom.schema_id
    return None

"""Core-domain fixtures used below a concrete frontend adapter."""

from __future__ import annotations

from collections.abc import Mapping

from scopecat.domain.program import DomainProgramDef
from scopecat.kernel.json_types import JsonValue
from scopecat.program.domain import DomainCall, create_domain_call_internal
from scopecat.program.operations import ComputeNodeInputValue
from scopecat.program.products import ModuleProductDecl, ProductValueSpec
from scopecat.records.execution import DomainExecutionId
from scopecat.sdk.domain.invocation import DomainInvocationIntent


def domain_execution_identity(
    *,
    run_id: str,
    logical_compute_node_id: str,
    invocation_id: str = "test-invocation",
    target_id: str = "test-target",
    target_intent: Mapping[str, JsonValue] | None = None,
) -> tuple[DomainInvocationIntent, DomainExecutionId]:
    """Build correlated durable invocation fixtures without a target payload."""

    compiler_id = "test-compiler"
    capability_fingerprint = "test-capability"
    artifact_id = "test-artifact"
    artifact_fingerprint = "test-artifact-fingerprint"
    result_contract_fingerprint = "test-result-contract"
    selected_target_intent = dict(target_intent or {})
    execution_summary: dict[str, JsonValue] = {}
    intent = DomainInvocationIntent.create(
        invocation_id=invocation_id,
        target_id=target_id,
        compiler_id=compiler_id,
        capability_fingerprint=capability_fingerprint,
        artifact_id=artifact_id,
        artifact_fingerprint=artifact_fingerprint,
        result_contract_fingerprint=result_contract_fingerprint,
        target_intent=selected_target_intent,
        execution_summary=execution_summary,
    )
    return (
        intent,
        DomainExecutionId(
            run_id=run_id,
            logical_compute_node_id=logical_compute_node_id,
            invocation_id=invocation_id,
            intent_fingerprint=intent.intent_fingerprint,
        ),
    )


def domain_call(
    program: DomainProgramDef,
    *,
    id: str = "call",
    inputs: Mapping[str, ComputeNodeInputValue] | None = None,
    compiler_inputs: Mapping[str, ComputeNodeInputValue] | None = None,
    products: Mapping[str, ModuleProductDecl] | None = None,
) -> DomainCall:
    """Build the native call a domain frontend would expose to authoring."""

    selected_products = products or {
        port.id: ModuleProductDecl(port.id, value_spec=ProductValueSpec())
        for port in program.result_ports
    }
    return create_domain_call_internal(
        program,
        id=id,
        inputs=inputs,
        compiler_inputs=compiler_inputs,
        result_products=selected_products,
    )

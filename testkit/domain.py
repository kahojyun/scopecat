"""Core-domain fixtures used below a concrete frontend adapter."""

from __future__ import annotations

from collections.abc import Mapping

from scopecat.domain.program import DomainProgramDef
from scopecat.program.domain import DomainCall, create_domain_call_internal
from scopecat.program.operations import ComputeNodeInputValue
from scopecat.program.products import ModuleProductDecl, ProductValueSpec


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

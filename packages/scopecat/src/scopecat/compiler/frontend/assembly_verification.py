"""Construction of the complete config-free assembly proof."""

from __future__ import annotations

from dataclasses import replace

from scopecat.compiler.frontend.assembly_lowering import (
    coerce_assembly_inputs,
    validate_assembly_entrypoint,
    validate_consumed_inputs,
)
from scopecat.compiler.frontend.elaboration import SemanticExperimentIR
from scopecat.compiler.frontend.graph_validation import (
    VerifiedAssembly,
    verify_assembly_graph,
)


def verify_assembly(assembly: SemanticExperimentIR) -> VerifiedAssembly:
    """Normalize and close every config-independent assembly invariant once."""

    validate_assembly_entrypoint(assembly)
    inputs = coerce_assembly_inputs(assembly.input_ports, assembly.inputs)
    normalized = replace(assembly, inputs=inputs)
    graph = verify_assembly_graph(normalized)
    validate_consumed_inputs(normalized, inputs)
    return VerifiedAssembly(source=normalized, graph=graph)


__all__ = ["verify_assembly"]

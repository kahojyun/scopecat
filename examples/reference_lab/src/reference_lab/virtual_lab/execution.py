"""Virtual execution adapter for the otherwise device-neutral lab compiler."""

from __future__ import annotations

from reference_lab.compiler import (
    QuantumRuntimeContext,
    QuantumRuntimeSelection,
)
from reference_lab.targets.list_mode import ListModeDomainRuntime
from reference_lab.virtual_lab.capture_plant import VirtualListModeDomainRuntime
from reference_lab.virtual_lab.quantum_responses import quantum_lab_response


def virtual_quantum_runtime(
    context: QuantumRuntimeContext,
) -> QuantumRuntimeSelection:
    """Select synthetic quantum responses only for the virtual application."""

    response = quantum_lab_response(
        context.program,
        context.points,
        context.entries,
        context.repetitions,
    )
    if response is None:
        return QuantumRuntimeSelection(ListModeDomainRuntime())
    return QuantumRuntimeSelection(
        runtime=VirtualListModeDomainRuntime(response),
        response_intent={
            "schema": "reference_lab.response.v1",
            "response_fingerprint": response.fingerprint,
        },
    )


__all__ = ["virtual_quantum_runtime"]

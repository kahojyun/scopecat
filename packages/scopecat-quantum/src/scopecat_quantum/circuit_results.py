"""Map prepared circuit-target results to Scopecat logical outputs.

This module is a thin quantum adapter over the public domain-preparation SDK.
It derives the complete target inventory from a sealed circuit-target batch;
core remains unaware of circuits, pulses, acquisition slots, and target-entry
structure.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat.sdk.domain import (
    DomainPointRef,
    DomainPreparationBuilder,
    DomainProductUseRef,
    DomainResultMapping,
)

from scopecat_quantum._ids import TargetCompileEntryId
from scopecat_quantum._target_results import (
    map_target_results,
    validate_compiled_target_request,
    validate_target_result_mapping,
)
from scopecat_quantum.circuit_targets import PreparedCircuitTargetBatch
from scopecat_quantum.targets import (
    CompiledTargetArtifact,
    TargetAcquisitionAddress,
    TargetArtifact,
)


@dataclass(frozen=True, slots=True)
class CircuitTargetEntryPointBinding:
    """Quantum adapter edge from one target entry to one logical point."""

    entry_id: TargetCompileEntryId
    point: DomainPointRef


@dataclass(frozen=True, slots=True)
class CircuitTargetAcquisitionUseBinding:
    """Quantum adapter edge from one acquisition address to one product use.

    The parent entry is part of ``address`` and is deliberately not repeated as
    caller-supplied data.
    """

    address: TargetAcquisitionAddress
    product_use: DomainProductUseRef


@dataclass(frozen=True, slots=True)
class CircuitTargetResultMapping:
    """Sealed exact mapping from one prepared quantum batch to selected outputs."""

    batch: PreparedCircuitTargetBatch
    domain_mapping: DomainResultMapping[
        TargetCompileEntryId,
        TargetAcquisitionAddress,
    ]

    def __post_init__(self) -> None:
        validate_target_result_mapping(self.batch.request, self.domain_mapping)


@dataclass(frozen=True, slots=True)
class CompiledCircuitTarget[ArtifactT: TargetArtifact]:
    """One compiled artifact correlated to an exact circuit result mapping.

    This is still a pure compilation proof.  It does not represent submission,
    execution, result acceptance, or product-value aggregation.
    """

    mapping: CircuitTargetResultMapping
    compiled: CompiledTargetArtifact[ArtifactT]

    def __post_init__(self) -> None:
        _validate_compiled_target_correlation(self.mapping, self.compiled)


def _validate_compiled_target_correlation[ArtifactT: TargetArtifact](
    mapping: CircuitTargetResultMapping,
    compiled: CompiledTargetArtifact[ArtifactT],
) -> None:
    validate_compiled_target_request(
        mapping.batch.request,
        compiled,
        family="circuit",
    )


def seal_circuit_target_result_mapping(
    preparation: DomainPreparationBuilder,
    batch: PreparedCircuitTargetBatch,
    entry_bindings: Sequence[CircuitTargetEntryPointBinding],
    acquisition_bindings: Sequence[CircuitTargetAcquisitionUseBinding],
) -> CircuitTargetResultMapping:
    """Close exact quantum entry/result coverage against core logical outputs."""

    selected_entry_bindings = tuple(entry_bindings)
    selected_acquisition_bindings = tuple(acquisition_bindings)

    domain_mapping = map_target_results(
        preparation,
        batch.request,
        tuple((binding.entry_id, binding.point) for binding in selected_entry_bindings),
        tuple(
            (binding.address, binding.product_use)
            for binding in selected_acquisition_bindings
        ),
    )
    return CircuitTargetResultMapping(
        batch,
        domain_mapping,
    )


__all__ = [
    "CircuitTargetAcquisitionUseBinding",
    "CircuitTargetEntryPointBinding",
    "CircuitTargetResultMapping",
    "CompiledCircuitTarget",
    "seal_circuit_target_result_mapping",
]

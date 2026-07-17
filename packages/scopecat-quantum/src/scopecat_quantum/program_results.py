"""Map prepared mixed-program target results to logical domain outputs.

The public mapping retains the sealed
:class:`~scopecat_quantum.program_targets.PreparedQuantumTargetBatch`, rather
than reducing it to a target request.  Entry-qualified acquisition addresses
therefore remain correlated with their source ``QuantumProgramId`` and mixed
gate/pulse provenance throughout compilation.

This module is deliberately independent of concrete compiler
implementations.  Compilation correlation operates on the domain-neutral
``CompiledTargetArtifact`` proof exposed by the quantum target boundary.
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
from scopecat_quantum.program_targets import PreparedQuantumTargetBatch
from scopecat_quantum.targets import (
    CompiledTargetArtifact,
    TargetAcquisitionAddress,
    TargetArtifact,
)


@dataclass(frozen=True, slots=True)
class QuantumTargetEntryPointBinding:
    """Adapter edge from one mixed-program target entry to one logical point."""

    entry_id: TargetCompileEntryId
    point: DomainPointRef


@dataclass(frozen=True, slots=True)
class QuantumTargetAcquisitionUseBinding:
    """Adapter edge from one qualified acquisition to one logical product use."""

    address: TargetAcquisitionAddress
    product_use: DomainProductUseRef


@dataclass(frozen=True, slots=True)
class QuantumTargetResultMapping:
    """Sealed exact mapping from one prepared mixed-program batch to outputs."""

    batch: PreparedQuantumTargetBatch
    domain_mapping: DomainResultMapping[
        TargetCompileEntryId,
        TargetAcquisitionAddress,
    ]

    def __post_init__(self) -> None:
        validate_target_result_mapping(self.batch.request, self.domain_mapping)


@dataclass(frozen=True, slots=True)
class CompiledQuantumTarget[ArtifactT: TargetArtifact]:
    """Compiled artifact correlated to one exact mixed-program result mapping."""

    mapping: QuantumTargetResultMapping
    compiled: CompiledTargetArtifact[ArtifactT]

    def __post_init__(self) -> None:
        _validate_compiled_target_correlation(self.mapping, self.compiled)


def seal_quantum_target_result_mapping(
    preparation: DomainPreparationBuilder,
    batch: PreparedQuantumTargetBatch,
    entry_bindings: Sequence[QuantumTargetEntryPointBinding],
    acquisition_bindings: Sequence[QuantumTargetAcquisitionUseBinding],
) -> QuantumTargetResultMapping:
    """Close exact target entry/result coverage against logical outputs."""

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
    return QuantumTargetResultMapping(batch, domain_mapping)


def _validate_compiled_target_correlation[ArtifactT: TargetArtifact](
    mapping: QuantumTargetResultMapping,
    compiled: CompiledTargetArtifact[ArtifactT],
) -> None:
    validate_compiled_target_request(
        mapping.batch.request,
        compiled,
        family="quantum",
    )

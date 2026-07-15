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
from typing import cast

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
    validate_target_acquisition_use_binding,
    validate_target_entry_point_binding,
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

    def __post_init__(self) -> None:
        validate_target_entry_point_binding(
            cast("object", self.entry_id),
            cast("object", self.point),
            family="quantum",
        )


@dataclass(frozen=True, slots=True)
class QuantumTargetAcquisitionUseBinding:
    """Adapter edge from one qualified acquisition to one logical product use."""

    address: TargetAcquisitionAddress
    product_use: DomainProductUseRef

    def __post_init__(self) -> None:
        validate_target_acquisition_use_binding(
            cast("object", self.address),
            cast("object", self.product_use),
            family="quantum",
        )


@dataclass(frozen=True, slots=True, init=False)
class QuantumTargetResultMapping:
    """Sealed exact mapping from one prepared mixed-program batch to outputs."""

    batch: PreparedQuantumTargetBatch
    domain_mapping: DomainResultMapping[
        TargetCompileEntryId,
        TargetAcquisitionAddress,
    ]

    def __init__(
        self,
        batch: PreparedQuantumTargetBatch,
        domain_mapping: DomainResultMapping[
            TargetCompileEntryId,
            TargetAcquisitionAddress,
        ],
    ) -> None:
        if not isinstance(cast("object", batch), PreparedQuantumTargetBatch):
            msg = "quantum target result mappings require a prepared batch"
            raise TypeError(msg)
        if not isinstance(cast("object", domain_mapping), DomainResultMapping):
            msg = "quantum target result mappings require a domain result mapping"
            raise TypeError(msg)
        validate_target_result_mapping(batch.request, domain_mapping)
        object.__setattr__(self, "batch", batch)
        object.__setattr__(self, "domain_mapping", domain_mapping)


@dataclass(frozen=True, slots=True, init=False)
class CompiledQuantumTarget[ArtifactT: TargetArtifact]:
    """Compiled artifact correlated to one exact mixed-program result mapping."""

    mapping: QuantumTargetResultMapping
    compiled: CompiledTargetArtifact[ArtifactT]

    def __init__(
        self,
        mapping: QuantumTargetResultMapping,
        compiled: CompiledTargetArtifact[ArtifactT],
    ) -> None:
        _validate_compiled_target_correlation(mapping, compiled)
        object.__setattr__(self, "mapping", mapping)
        object.__setattr__(self, "compiled", compiled)


def bind_compiled_quantum_target[ArtifactT: TargetArtifact](
    mapping: QuantumTargetResultMapping,
    compiled: CompiledTargetArtifact[ArtifactT],
) -> CompiledQuantumTarget[ArtifactT]:
    """Bind one checked target artifact to its exact mixed-program batch."""

    if not isinstance(cast("object", mapping), QuantumTargetResultMapping):
        msg = "compiled quantum targets require a QuantumTargetResultMapping"
        raise TypeError(msg)
    if not isinstance(cast("object", compiled), CompiledTargetArtifact):
        msg = "compiled quantum targets require a CompiledTargetArtifact"
        raise TypeError(msg)
    return CompiledQuantumTarget(mapping, compiled)


def seal_quantum_target_result_mapping(
    preparation: DomainPreparationBuilder,
    batch: PreparedQuantumTargetBatch,
    entry_bindings: Sequence[QuantumTargetEntryPointBinding],
    acquisition_bindings: Sequence[QuantumTargetAcquisitionUseBinding],
) -> QuantumTargetResultMapping:
    """Close exact target entry/result coverage against logical outputs."""

    if not isinstance(cast("object", preparation), DomainPreparationBuilder):
        msg = "quantum target result mapping requires a DomainPreparationBuilder"
        raise TypeError(msg)
    if not isinstance(cast("object", batch), PreparedQuantumTargetBatch):
        msg = "quantum target result mapping requires a prepared batch"
        raise TypeError(msg)

    selected_entry_bindings = tuple(entry_bindings)
    if any(
        not isinstance(cast("object", binding), QuantumTargetEntryPointBinding)
        for binding in selected_entry_bindings
    ):
        msg = "entry bindings require QuantumTargetEntryPointBinding values"
        raise TypeError(msg)
    selected_acquisition_bindings = tuple(acquisition_bindings)
    if any(
        not isinstance(
            cast("object", binding),
            QuantumTargetAcquisitionUseBinding,
        )
        for binding in selected_acquisition_bindings
    ):
        msg = "acquisition bindings require QuantumTargetAcquisitionUseBinding values"
        raise TypeError(msg)

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
    if not isinstance(cast("object", mapping), QuantumTargetResultMapping):
        msg = "compiled quantum targets require a quantum result mapping"
        raise TypeError(msg)
    if not isinstance(cast("object", compiled), CompiledTargetArtifact):
        msg = "compiled quantum targets require a compiled target artifact"
        raise TypeError(msg)

    validate_compiled_target_request(
        mapping.batch.request,
        compiled,
        family="quantum",
    )


__all__ = [
    "CompiledQuantumTarget",
    "QuantumTargetAcquisitionUseBinding",
    "QuantumTargetEntryPointBinding",
    "QuantumTargetResultMapping",
    "bind_compiled_quantum_target",
    "seal_quantum_target_result_mapping",
]

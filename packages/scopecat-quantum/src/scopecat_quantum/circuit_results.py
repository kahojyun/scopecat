"""Map prepared circuit-target results to Scopecat logical outputs.

This module is a thin quantum adapter over the public domain-preparation SDK.
It derives the complete target inventory from a sealed circuit-target batch;
core remains unaware of circuits, pulses, acquisition slots, and target-entry
structure.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from scopecat.sdk.domain import (
    DomainEntryPointBinding,
    DomainPointRef,
    DomainPreparationBuilder,
    DomainProductUseRef,
    DomainResultMapping,
    DomainResultUseBinding,
    DomainTargetEntry,
)

from scopecat_quantum._ids import TargetCompileEntryId
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

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.entry_id), TargetCompileEntryId):
            msg = "circuit target entry-point bindings require a TargetCompileEntryId"
            raise TypeError(msg)
        if not isinstance(cast("object", self.point), DomainPointRef):
            msg = "circuit target entry-point bindings require a DomainPointRef"
            raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class CircuitTargetAcquisitionUseBinding:
    """Quantum adapter edge from one acquisition address to one product use.

    The parent entry is part of ``address`` and is deliberately not repeated as
    caller-supplied data.
    """

    address: TargetAcquisitionAddress
    product_use: DomainProductUseRef

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.address), TargetAcquisitionAddress):
            msg = (
                "circuit target acquisition-use bindings require a "
                "TargetAcquisitionAddress"
            )
            raise TypeError(msg)
        if not isinstance(cast("object", self.product_use), DomainProductUseRef):
            msg = (
                "circuit target acquisition-use bindings require a DomainProductUseRef"
            )
            raise TypeError(msg)


@dataclass(frozen=True, slots=True, init=False)
class CircuitTargetResultMapping:
    """Sealed exact mapping from one prepared quantum batch to selected outputs."""

    batch: PreparedCircuitTargetBatch
    domain_mapping: DomainResultMapping[
        TargetCompileEntryId,
        TargetAcquisitionAddress,
    ]

    def __init__(
        self,
        batch: PreparedCircuitTargetBatch,
        domain_mapping: DomainResultMapping[
            TargetCompileEntryId,
            TargetAcquisitionAddress,
        ],
    ) -> None:
        if not isinstance(cast("object", batch), PreparedCircuitTargetBatch):
            msg = "circuit target result mappings require a prepared batch"
            raise TypeError(msg)
        if not isinstance(
            cast("object", domain_mapping),
            DomainResultMapping,
        ):
            msg = "circuit target result mappings require a domain result mapping"
            raise TypeError(msg)
        expected_adapter_inventory = tuple(
            (entry.id, entry.acquisition_addresses) for entry in batch.entries
        )
        mapped_target_inventory = tuple(
            (entry.entry_address, entry.result_addresses)
            for entry in domain_mapping.target_entries
        )
        if mapped_target_inventory != expected_adapter_inventory:
            msg = "domain mapping must retain the exact prepared batch inventory"
            raise ValueError(msg)
        expected_entry_ids = tuple(entry.id for entry in batch.entries)
        if {entry.entry_address for entry in domain_mapping.entries} != set(
            expected_entry_ids
        ):
            msg = "domain mapping must exactly cover prepared target entries"
            raise ValueError(msg)
        expected_addresses = batch.acquisition_addresses
        if {result.result_address for result in domain_mapping.results} != set(
            expected_addresses
        ):
            msg = "domain mapping must exactly cover prepared acquisition addresses"
            raise ValueError(msg)
        if any(
            result.entry_address != result.result_address.entry_id
            for result in domain_mapping.results
        ):
            msg = "domain result parent entries must derive from quantum addresses"
            raise ValueError(msg)
        object.__setattr__(self, "batch", batch)
        object.__setattr__(self, "domain_mapping", domain_mapping)


@dataclass(frozen=True, slots=True, init=False)
class CompiledCircuitTarget[ArtifactT: TargetArtifact]:
    """One compiled artifact correlated to an exact circuit result mapping.

    This is still a pure compilation proof.  It does not represent submission,
    execution, result acceptance, or product-value aggregation.
    """

    mapping: CircuitTargetResultMapping
    compiled: CompiledTargetArtifact[ArtifactT]

    def __init__(
        self,
        mapping: CircuitTargetResultMapping,
        compiled: CompiledTargetArtifact[ArtifactT],
    ) -> None:
        _validate_compiled_target_correlation(mapping, compiled)
        object.__setattr__(self, "mapping", mapping)
        object.__setattr__(self, "compiled", compiled)


def bind_compiled_circuit_target[ArtifactT: TargetArtifact](
    mapping: CircuitTargetResultMapping,
    compiled: CompiledTargetArtifact[ArtifactT],
) -> CompiledCircuitTarget[ArtifactT]:
    """Bind one checked target artifact to its exact prepared circuit batch."""

    if not isinstance(cast("object", mapping), CircuitTargetResultMapping):
        msg = "compiled circuit targets require a CircuitTargetResultMapping"
        raise TypeError(msg)
    if not isinstance(cast("object", compiled), CompiledTargetArtifact):
        msg = "compiled circuit targets require a CompiledTargetArtifact"
        raise TypeError(msg)
    return CompiledCircuitTarget(
        mapping,
        compiled,
    )


def _validate_compiled_target_correlation[ArtifactT: TargetArtifact](
    mapping: CircuitTargetResultMapping,
    compiled: CompiledTargetArtifact[ArtifactT],
) -> None:
    if not isinstance(cast("object", mapping), CircuitTargetResultMapping):
        msg = "compiled circuit targets require a circuit result mapping"
        raise TypeError(msg)
    if not isinstance(cast("object", compiled), CompiledTargetArtifact):
        msg = "compiled circuit targets require a compiled target artifact"
        raise TypeError(msg)

    request = mapping.batch.request
    if compiled.request != request:
        msg = "compiled target request must exactly match the mapped circuit batch"
        raise ValueError(msg)
    expected_entry_ids = tuple(entry.id for entry in request.entries)
    if (
        compiled.target_id != request.target_id
        or compiled.compiler_id != request.compiler_id
        or compiled.capability_fingerprint != request.capability_fingerprint
        or compiled.source_entry_ids != expected_entry_ids
        or compiled.repetitions != request.repetitions
    ):
        msg = "compiled target provenance does not match its retained request"
        raise ValueError(msg)


def seal_circuit_target_result_mapping(
    preparation: DomainPreparationBuilder,
    batch: PreparedCircuitTargetBatch,
    entry_bindings: Sequence[CircuitTargetEntryPointBinding],
    acquisition_bindings: Sequence[CircuitTargetAcquisitionUseBinding],
) -> CircuitTargetResultMapping:
    """Close exact quantum entry/result coverage against core logical outputs."""

    if not isinstance(cast("object", preparation), DomainPreparationBuilder):
        msg = "circuit target result mapping requires a DomainPreparationBuilder"
        raise TypeError(msg)
    if not isinstance(cast("object", batch), PreparedCircuitTargetBatch):
        msg = "circuit target result mapping requires a prepared batch"
        raise TypeError(msg)
    selected_entry_bindings = tuple(entry_bindings)
    if any(
        not isinstance(cast("object", binding), CircuitTargetEntryPointBinding)
        for binding in selected_entry_bindings
    ):
        msg = "entry bindings require CircuitTargetEntryPointBinding values"
        raise TypeError(msg)
    selected_acquisition_bindings = tuple(acquisition_bindings)
    if any(
        not isinstance(
            cast("object", binding),
            CircuitTargetAcquisitionUseBinding,
        )
        for binding in selected_acquisition_bindings
    ):
        msg = "acquisition bindings require CircuitTargetAcquisitionUseBinding values"
        raise TypeError(msg)

    domain_mapping = preparation.map_measurements(
        entries=tuple(
            DomainTargetEntry(
                entry_address=entry.id,
                result_addresses=entry.acquisition_addresses,
            )
            for entry in batch.entries
        ),
        entry_points=tuple(
            DomainEntryPointBinding(
                entry_address=binding.entry_id,
                point=binding.point,
            )
            for binding in selected_entry_bindings
        ),
        results=tuple(
            DomainResultUseBinding(
                entry_address=binding.address.entry_id,
                result_address=binding.address,
                product_use=binding.product_use,
            )
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
    "bind_compiled_circuit_target",
    "seal_circuit_target_result_mapping",
]

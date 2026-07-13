"""Map prepared circuit-target results to Scopecat logical outputs.

This module is a thin quantum adapter over :mod:`scopecat.domain_invocation`.
It derives the complete adapter inventory from a sealed circuit-target batch;
core remains unaware of circuits, pulses, acquisition slots, and target entry
structure.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from scopecat.domain_invocation import (
    AdapterEntryResults,
    ClosedDomainEntry,
    ClosedDomainResult,
    ClosedDomainResultMapping,
    EntryPointBinding,
    LogicalPointId,
    MaterializedLinkedPoints,
    ProductUseId,
    ResultUseBinding,
    seal_domain_result_mapping,
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
    logical_point_id: LogicalPointId

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.entry_id), TargetCompileEntryId):
            msg = "circuit target entry-point bindings require a TargetCompileEntryId"
            raise TypeError(msg)
        if not isinstance(cast("object", self.logical_point_id), LogicalPointId):
            msg = "circuit target entry-point bindings require a LogicalPointId"
            raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class CircuitTargetAcquisitionUseBinding:
    """Quantum adapter edge from one acquisition address to one product use.

    The parent entry is part of ``address`` and is deliberately not repeated as
    caller-supplied data.
    """

    address: TargetAcquisitionAddress
    product_use_id: ProductUseId

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.address), TargetAcquisitionAddress):
            msg = (
                "circuit target acquisition-use bindings require a "
                "TargetAcquisitionAddress"
            )
            raise TypeError(msg)
        if not isinstance(cast("object", self.product_use_id), ProductUseId):
            msg = "circuit target acquisition-use bindings require a ProductUseId"
            raise TypeError(msg)


@dataclass(frozen=True, slots=True, init=False)
class CircuitTargetResultMapping:
    """Sealed exact mapping from one prepared quantum batch to selected outputs."""

    batch: PreparedCircuitTargetBatch
    core_mapping: ClosedDomainResultMapping[
        TargetCompileEntryId,
        TargetAcquisitionAddress,
    ]

    def __init__(
        self,
        batch: PreparedCircuitTargetBatch,
        core_mapping: ClosedDomainResultMapping[
            TargetCompileEntryId,
            TargetAcquisitionAddress,
        ],
    ) -> None:
        if not isinstance(cast("object", batch), PreparedCircuitTargetBatch):
            msg = "circuit target result mappings require a prepared batch"
            raise TypeError(msg)
        if not isinstance(
            cast("object", core_mapping),
            ClosedDomainResultMapping,
        ):
            msg = "circuit target result mappings require a closed core mapping"
            raise TypeError(msg)
        expected_adapter_entries = _adapter_entries(batch)
        if core_mapping.adapter_entries != expected_adapter_entries:
            msg = "core mapping must retain the exact prepared batch inventory"
            raise ValueError(msg)
        expected_entry_ids = tuple(entry.id for entry in batch.entries)
        if {entry.entry_address for entry in core_mapping.entries} != set(
            expected_entry_ids
        ):
            msg = "core mapping must exactly cover prepared target entries"
            raise ValueError(msg)
        expected_addresses = batch.acquisition_addresses
        if {result.result_address for result in core_mapping.results} != set(
            expected_addresses
        ):
            msg = "core mapping must exactly cover prepared acquisition addresses"
            raise ValueError(msg)
        if any(
            result.entry_address != result.result_address.entry_id
            for result in core_mapping.results
        ):
            msg = "core result parent entries must be derived from quantum addresses"
            raise ValueError(msg)
        object.__setattr__(self, "batch", batch)
        object.__setattr__(self, "core_mapping", core_mapping)

    @property
    def linked_points(self) -> MaterializedLinkedPoints:
        return self.core_mapping.linked_points

    @property
    def entries(
        self,
    ) -> tuple[
        ClosedDomainEntry[TargetCompileEntryId, TargetAcquisitionAddress],
        ...,
    ]:
        return self.core_mapping.entries

    @property
    def results(
        self,
    ) -> tuple[
        ClosedDomainResult[TargetCompileEntryId, TargetAcquisitionAddress],
        ...,
    ]:
        return self.core_mapping.results

    @property
    def selected_product_use_ids(self) -> tuple[ProductUseId, ...]:
        """Return the selected subset in linked-program canonical order."""

        return self.core_mapping.selected_product_use_ids

    def entry_for_id(
        self,
        entry_id: TargetCompileEntryId,
    ) -> ClosedDomainEntry[TargetCompileEntryId, TargetAcquisitionAddress]:
        return self.core_mapping.entry_for_address(entry_id)

    def result_for_address(
        self,
        address: TargetAcquisitionAddress,
    ) -> ClosedDomainResult[TargetCompileEntryId, TargetAcquisitionAddress]:
        return self.core_mapping.result_for_address(address)

    def result_for_output(
        self,
        logical_point_id: LogicalPointId,
        product_use_id: ProductUseId,
    ) -> ClosedDomainResult[TargetCompileEntryId, TargetAcquisitionAddress]:
        return self.core_mapping.result_for_output(
            logical_point_id,
            product_use_id,
        )


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
    linked_points: MaterializedLinkedPoints,
    batch: PreparedCircuitTargetBatch,
    entry_bindings: Sequence[CircuitTargetEntryPointBinding],
    acquisition_bindings: Sequence[CircuitTargetAcquisitionUseBinding],
) -> CircuitTargetResultMapping:
    """Close exact quantum entry/result coverage against core logical outputs."""

    if not isinstance(cast("object", linked_points), MaterializedLinkedPoints):
        msg = "circuit target result mapping requires MaterializedLinkedPoints"
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

    adapter_entries = _adapter_entries(batch)
    selected_product_use_ids = tuple(
        dict.fromkeys(
            binding.product_use_id for binding in selected_acquisition_bindings
        )
    )
    core_mapping = seal_domain_result_mapping(
        linked_points,
        selected_product_use_ids,
        adapter_entries,
        tuple(
            EntryPointBinding(
                entry_address=binding.entry_id,
                logical_point_id=binding.logical_point_id,
            )
            for binding in selected_entry_bindings
        ),
        tuple(
            ResultUseBinding(
                entry_address=binding.address.entry_id,
                result_address=binding.address,
                product_use_id=binding.product_use_id,
            )
            for binding in selected_acquisition_bindings
        ),
    )
    return CircuitTargetResultMapping(
        batch,
        core_mapping,
    )


def _adapter_entries(
    batch: PreparedCircuitTargetBatch,
) -> tuple[
    AdapterEntryResults[TargetCompileEntryId, TargetAcquisitionAddress],
    ...,
]:
    return tuple(
        AdapterEntryResults(
            entry_address=entry.id,
            result_addresses=entry.acquisition_addresses,
        )
        for entry in batch.entries
    )


__all__ = [
    "CircuitTargetAcquisitionUseBinding",
    "CircuitTargetEntryPointBinding",
    "CircuitTargetResultMapping",
    "CompiledCircuitTarget",
    "bind_compiled_circuit_target",
    "seal_circuit_target_result_mapping",
]

"""Map prepared target results to logical domain outputs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat.sdk.domain import (
    DomainPointRef,
    DomainPreparationBuilder,
    DomainProductUseRef,
    DomainResultBinding,
    DomainResultMapping,
)

from scopecat_quantum._ids import TargetCompileEntryId
from scopecat_quantum.program_targets import PreparedQuantumTargetBatch
from scopecat_quantum.targets import (
    TargetAcquisitionAddress,
    TargetArtifact,
)


@dataclass(frozen=True, slots=True)
class QuantumTargetEntryPointBinding:
    """Adapter edge from one mixed-program target entry to one logical point."""

    entry_id: TargetCompileEntryId
    point: DomainPointRef


@dataclass(frozen=True, slots=True)
class QuantumTargetResultUseBinding:
    """Adapter edge from one acquisition to one logical product use."""

    address: TargetAcquisitionAddress
    product_use: DomainProductUseRef


@dataclass(frozen=True, slots=True)
class MappedQuantumTarget[ArtifactT: TargetArtifact]:
    """One opaque target artifact and its exact logical result mapping."""

    artifact: ArtifactT
    mapping: DomainResultMapping[TargetAcquisitionAddress]


def seal_quantum_target_result_mapping(
    preparation: DomainPreparationBuilder,
    batch: PreparedQuantumTargetBatch,
    entry_bindings: Sequence[QuantumTargetEntryPointBinding],
    result_bindings: Sequence[QuantumTargetResultUseBinding],
) -> DomainResultMapping[TargetAcquisitionAddress]:
    """Close exact target entry/result coverage against logical outputs."""

    selected_entry_bindings = tuple(entry_bindings)
    selected_result_bindings = tuple(result_bindings)
    point_by_entry = {
        binding.entry_id: binding.point for binding in selected_entry_bindings
    }
    expected_entry_ids = batch.request.source_entry_ids
    if len(point_by_entry) != len(selected_entry_bindings) or set(
        point_by_entry
    ) != set(expected_entry_ids):
        raise ValueError("quantum entry-point bindings must cover target entries")
    domain_mapping = preparation.map_measurements(
        results=tuple(
            DomainResultBinding(
                result_address=binding.address,
                point=point_by_entry[binding.address.entry_id],
                product_use=binding.product_use,
            )
            for binding in selected_result_bindings
        )
    )
    expected_addresses = batch.request.acquisition_addresses
    mapped_addresses = tuple(result.result_address for result in domain_mapping.results)
    if len(mapped_addresses) != len(expected_addresses) or set(mapped_addresses) != set(
        expected_addresses
    ):
        raise ValueError(
            "domain mapping must exactly cover prepared acquisition addresses"
        )
    return domain_mapping

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
class QuantumTargetResultAddress:
    """One logical result assembled from one or more target acquisitions."""

    acquisitions: tuple[TargetAcquisitionAddress, ...]

    def __post_init__(self) -> None:
        if not self.acquisitions:
            raise ValueError("quantum result addresses require acquisitions")
        if len(set(self.acquisitions)) != len(self.acquisitions):
            raise ValueError("quantum result addresses require unique acquisitions")
        if len({address.entry_id for address in self.acquisitions}) != 1:
            raise ValueError("one quantum result address must belong to one entry")

    @property
    def entry_id(self) -> TargetCompileEntryId:
        """Return the target entry shared by every acquisition in the group."""

        return self.acquisitions[0].entry_id


@dataclass(frozen=True, slots=True)
class QuantumTargetResultUseBinding:
    """Adapter edge from one acquisition to one logical product use."""

    address: QuantumTargetResultAddress
    product_use: DomainProductUseRef


@dataclass(frozen=True, slots=True)
class MappedQuantumTarget[ArtifactT: TargetArtifact]:
    """One opaque target artifact and its exact logical result mapping."""

    artifact: ArtifactT
    mapping: DomainResultMapping[QuantumTargetResultAddress]

    @property
    def acquisition_addresses(self) -> tuple[TargetAcquisitionAddress, ...]:
        """Return raw target addresses in logical result order."""

        return tuple(
            address
            for result in self.mapping.results
            for address in result.result_address.acquisitions
        )


def seal_quantum_target_result_mapping(
    preparation: DomainPreparationBuilder,
    batch: PreparedQuantumTargetBatch,
    entry_bindings: Sequence[QuantumTargetEntryPointBinding],
    result_bindings: Sequence[QuantumTargetResultUseBinding],
) -> DomainResultMapping[QuantumTargetResultAddress]:
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
    mapped_addresses = tuple(
        address
        for result in domain_mapping.results
        for address in result.result_address.acquisitions
    )
    if len(mapped_addresses) != len(expected_addresses) or set(mapped_addresses) != set(
        expected_addresses
    ):
        raise ValueError(
            "domain mapping must exactly cover prepared acquisition addresses"
        )
    return domain_mapping

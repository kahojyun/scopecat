"""Private result-mapping kernel shared by quantum authoring surfaces.

Circuit and mixed-program batches retain distinct public proof types, while
both lower to the same target request and SDK result-address vocabulary.  This
module owns that common algorithm.  Callers validate their public ingress
types once, then pass the already sealed request and normalized binding edges
here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

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
from scopecat_quantum.targets import (
    CompiledTargetArtifact,
    TargetAcquisitionAddress,
    TargetArtifact,
    TargetCompileRequest,
)

type TargetResultFamily = Literal["circuit", "quantum"]
type TargetEntryPoint = tuple[TargetCompileEntryId, DomainPointRef]
type TargetAcquisitionUse = tuple[TargetAcquisitionAddress, DomainProductUseRef]


def validate_target_entry_point_binding(
    entry_id: object,
    point: object,
    *,
    family: TargetResultFamily,
) -> None:
    """Validate one authoring-surface edge at its public ingress."""

    if not isinstance(entry_id, TargetCompileEntryId):
        msg = f"{family} target entry-point bindings require a TargetCompileEntryId"
        raise TypeError(msg)
    if not isinstance(point, DomainPointRef):
        msg = f"{family} target entry-point bindings require a DomainPointRef"
        raise TypeError(msg)


def validate_target_acquisition_use_binding(
    address: object,
    product_use: object,
    *,
    family: TargetResultFamily,
) -> None:
    """Validate one qualified-result edge at its public ingress."""

    if not isinstance(address, TargetAcquisitionAddress):
        msg = (
            f"{family} target acquisition-use bindings require a "
            "TargetAcquisitionAddress"
        )
        raise TypeError(msg)
    if not isinstance(product_use, DomainProductUseRef):
        msg = f"{family} target acquisition-use bindings require a DomainProductUseRef"
        raise TypeError(msg)


def map_target_results(
    preparation: DomainPreparationBuilder,
    request: TargetCompileRequest,
    entry_points: Sequence[TargetEntryPoint],
    acquisition_uses: Sequence[TargetAcquisitionUse],
) -> DomainResultMapping[TargetCompileEntryId, TargetAcquisitionAddress]:
    """Map one sealed target request inventory to exact logical outputs."""

    return preparation.map_measurements(
        entries=tuple(
            DomainTargetEntry(
                entry_address=entry.id,
                result_addresses=entry.acquisition_addresses,
            )
            for entry in request.entries
        ),
        entry_points=tuple(
            DomainEntryPointBinding(entry_address=entry_id, point=point)
            for entry_id, point in entry_points
        ),
        results=tuple(
            DomainResultUseBinding(
                entry_address=address.entry_id,
                result_address=address,
                product_use=product_use,
            )
            for address, product_use in acquisition_uses
        ),
    )


def validate_target_result_mapping(
    request: TargetCompileRequest,
    domain_mapping: DomainResultMapping[
        TargetCompileEntryId,
        TargetAcquisitionAddress,
    ],
) -> None:
    """Bind independently produced SDK mapping evidence to one request."""

    expected_inventory = tuple(
        (entry.id, entry.acquisition_addresses) for entry in request.entries
    )
    mapped_inventory = tuple(
        (entry.entry_address, entry.result_addresses)
        for entry in domain_mapping.target_entries
    )
    if mapped_inventory != expected_inventory:
        msg = "domain mapping must retain the exact prepared batch inventory"
        raise ValueError(msg)

    expected_entry_ids = tuple(entry.id for entry in request.entries)
    mapped_entry_ids = tuple(entry.entry_address for entry in domain_mapping.entries)
    if len(mapped_entry_ids) != len(expected_entry_ids) or set(mapped_entry_ids) != set(
        expected_entry_ids
    ):
        msg = "domain mapping must exactly cover prepared target entries"
        raise ValueError(msg)

    expected_addresses = request.acquisition_addresses
    mapped_addresses = tuple(result.result_address for result in domain_mapping.results)
    if len(mapped_addresses) != len(expected_addresses) or set(mapped_addresses) != set(
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


def validate_compiled_target_request[ArtifactT: TargetArtifact](
    request: TargetCompileRequest,
    compiled: CompiledTargetArtifact[ArtifactT],
    *,
    family: TargetResultFamily,
) -> None:
    """Bind a checked compiled artifact to its exact retained request.

    ``CompiledTargetArtifact`` is frozen trusted transient state.  Its target,
    compiler, capability, source-entry and repetition properties derive from
    ``request``, so request equality closes the correlation without repeating
    those already established invariants.
    """

    if compiled.request != request:
        msg = f"compiled target request must exactly match the mapped {family} batch"
        raise ValueError(msg)

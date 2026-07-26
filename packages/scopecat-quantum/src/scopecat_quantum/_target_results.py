"""Private result-mapping kernel for quantum target batches."""

from __future__ import annotations

from collections.abc import Sequence

from scopecat.sdk.domain import (
    DomainPointRef,
    DomainPreparationBuilder,
    DomainProductUseRef,
    DomainResultBinding,
    DomainResultMapping,
)

from scopecat_quantum._ids import TargetCompileEntryId
from scopecat_quantum.targets import (
    CompiledTargetArtifact,
    TargetArtifact,
    TargetCompileRequest,
    TargetResultAddress,
    target_result_acquisition_addresses,
    target_result_entry_id,
)

type TargetEntryPoint = tuple[TargetCompileEntryId, DomainPointRef]
type TargetResultUse = tuple[TargetResultAddress, DomainProductUseRef]


def map_target_results(
    preparation: DomainPreparationBuilder,
    request: TargetCompileRequest,
    entry_points: Sequence[TargetEntryPoint],
    result_uses: Sequence[TargetResultUse],
) -> DomainResultMapping[TargetResultAddress]:
    """Map one sealed target request inventory to exact logical outputs."""

    point_by_entry = dict(entry_points)
    expected_entry_ids = tuple(entry.id for entry in request.entries)
    if len(point_by_entry) != len(entry_points) or set(point_by_entry) != set(
        expected_entry_ids
    ):
        raise ValueError("quantum entry-point bindings must cover target entries")
    return preparation.map_measurements(
        results=tuple(
            DomainResultBinding(
                result_address=address,
                point=point_by_entry[target_result_entry_id(address)],
                product_use=product_use,
            )
            for address, product_use in result_uses
        ),
    )


def validate_target_result_mapping(
    request: TargetCompileRequest,
    domain_mapping: DomainResultMapping[TargetResultAddress],
) -> None:
    """Bind independently produced SDK mapping evidence to one request."""

    expected_addresses = request.acquisition_addresses
    mapped_addresses = tuple(
        address
        for result in domain_mapping.results
        for address in target_result_acquisition_addresses(result.result_address)
    )
    if len(mapped_addresses) != len(expected_addresses) or set(mapped_addresses) != set(
        expected_addresses
    ):
        msg = "domain mapping must exactly cover prepared acquisition addresses"
        raise ValueError(msg)


def validate_compiled_target_request[ArtifactT: TargetArtifact](
    request: TargetCompileRequest,
    compiled: CompiledTargetArtifact[ArtifactT],
) -> None:
    """Bind a checked compiled artifact to its exact retained request.

    ``CompiledTargetArtifact`` is frozen trusted transient state.  Its target,
    compiler, capability, source-entry and repetition properties derive from
    ``request``, so request equality closes the correlation without repeating
    those already established invariants.
    """

    if compiled.request != request:
        msg = "compiled target request must exactly match the mapped quantum batch"
        raise ValueError(msg)

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
    DomainPointRef,
    DomainPreparationBuilder,
    DomainProductUseRef,
    DomainResultBinding,
    DomainResultMapping,
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


def map_target_results(
    preparation: DomainPreparationBuilder,
    request: TargetCompileRequest,
    entry_points: Sequence[TargetEntryPoint],
    acquisition_uses: Sequence[TargetAcquisitionUse],
) -> DomainResultMapping[TargetAcquisitionAddress]:
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
                point=point_by_entry[address.entry_id],
                product_use=product_use,
            )
            for address, product_use in acquisition_uses
        ),
    )


def validate_target_result_mapping(
    request: TargetCompileRequest,
    domain_mapping: DomainResultMapping[TargetAcquisitionAddress],
) -> None:
    """Bind independently produced SDK mapping evidence to one request."""

    expected_addresses = request.acquisition_addresses
    mapped_addresses = tuple(result.result_address for result in domain_mapping.results)
    if len(mapped_addresses) != len(expected_addresses) or set(mapped_addresses) != set(
        expected_addresses
    ):
        msg = "domain mapping must exactly cover prepared acquisition addresses"
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

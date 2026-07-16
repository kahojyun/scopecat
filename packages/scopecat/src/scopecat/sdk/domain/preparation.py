"""Builder facade for closing one selected domain batch before effects."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from scopecat.measurements.host_transforms import (
    BoundHostMeasurementTransformPlan,
    HostMeasurementTransformCall,
    HostMeasurementTransformFragmentBinding,
    HostMeasurementTransformImplementation,
    HostMeasurementTransformImplementationBinding,
    bind_host_measurement_transforms,
    select_host_measurement_transforms,
)
from scopecat.measurements.transform_model import MeasurementTransformDef
from scopecat.measurements.transform_verification import (
    verify_measurement_transform_graph,
)
from scopecat.measurements.values import (
    BoundDomainMeasurementValueFragment,
    ProductValueFragmentDef,
    bind_domain_output_fragment,
    select_measurement_value_assembly,
)
from scopecat.planning.coverage import ExecutionResourceClaim
from scopecat.records.measurement import MeasurementValue
from scopecat.sdk.domain._bridge import point_id, product_use_id
from scopecat.sdk.domain._measurement_bridge import lower_domain_host_transform_binding
from scopecat.sdk.domain.context import DomainBatchContext
from scopecat.sdk.domain.execution import (
    ErasedDomainInvocation,
    ErasedDomainRealizer,
    ErasedDomainRuntime,
    PreparedDomainExecution,
)
from scopecat.sdk.domain.invocation import (
    AdapterEntryResults,
    ClosedDomainOutputValues,
    ClosedDomainResultMapping,
    DomainOutputValue,
    EntryPointBinding,
    ResultUseBinding,
    SelectedDomainMeasurementOutputs,
    close_domain_invocation,
    seal_domain_output_values,
    seal_domain_result_mapping,
)
from scopecat.sdk.domain.job import (
    DomainInvocationSpec,
    DomainResourceClaim,
    DomainResultValue,
)
from scopecat.sdk.domain.measurements import DomainHostTransformBinding
from scopecat.sdk.domain.runtime import CorrelatedDomainFetch, DomainRuntime
from scopecat.sdk.domain.view import DomainPointRef, DomainProductUseRef


@dataclass(frozen=True, slots=True)
class DomainTargetEntry[EntryAddressT: Hashable, ResultAddressT: Hashable]:
    """One target entry and its complete physical result-address inventory."""

    entry_address: EntryAddressT
    result_addresses: tuple[ResultAddressT, ...] = ()

    def __post_init__(self) -> None:
        if len(self.result_addresses) != len(set(self.result_addresses)):
            msg = "domain target result addresses must be unique within an entry"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class DomainEntryPointBinding[EntryAddressT: Hashable]:
    """Target entry edge to one SDK-owned logical point reference."""

    entry_address: EntryAddressT
    point: DomainPointRef


@dataclass(frozen=True, slots=True)
class DomainResultUseBinding[EntryAddressT: Hashable, ResultAddressT: Hashable]:
    """Physical result edge to one SDK-owned logical product occurrence."""

    entry_address: EntryAddressT
    result_address: ResultAddressT
    product_use: DomainProductUseRef


@dataclass(frozen=True, slots=True)
class DomainMappedResult[EntryAddressT: Hashable, ResultAddressT: Hashable]:
    """One physical result and every SDK-owned logical occurrence it supplies."""

    entry_address: EntryAddressT
    result_address: ResultAddressT
    point: DomainPointRef
    product_uses: tuple[DomainProductUseRef, ...]


@dataclass(frozen=True, slots=True)
class DomainMappedEntry[EntryAddressT: Hashable, ResultAddressT: Hashable]:
    """One target entry in canonical logical-point order."""

    entry_address: EntryAddressT
    point: DomainPointRef
    results: tuple[DomainMappedResult[EntryAddressT, ResultAddressT], ...]


@dataclass(frozen=True, slots=True)
class DomainResultMapping[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
]:
    """Exact public inventory from physical results to SDK-owned references.

    ``target_entries`` retains target order. ``entries`` retains canonical
    logical-point order, while ``results`` retains canonical product-use order.
    All point and product-use values are the exact references assembled for the
    preparation context; callers never need compiler-owned identities.
    """

    context: DomainBatchContext
    product_uses: tuple[DomainProductUseRef, ...]
    target_entries: tuple[DomainTargetEntry[EntryAddressT, ResultAddressT], ...]
    entries: tuple[DomainMappedEntry[EntryAddressT, ResultAddressT], ...]
    results: tuple[DomainMappedResult[EntryAddressT, ResultAddressT], ...]
    result_by_address: Mapping[
        ResultAddressT,
        DomainMappedResult[EntryAddressT, ResultAddressT],
    ] = field(repr=False, compare=False)
    result_by_output_identity: Mapping[
        tuple[int, int],
        DomainMappedResult[EntryAddressT, ResultAddressT],
    ] = field(repr=False, compare=False)
    native: ClosedDomainResultMapping[EntryAddressT, ResultAddressT] = field(
        repr=False,
        compare=False,
    )

    def result_for_address(
        self,
        result_address: ResultAddressT,
    ) -> DomainMappedResult[EntryAddressT, ResultAddressT]:
        """Return the canonical result for one target-owned physical address."""

        try:
            return self.result_by_address[result_address]
        except KeyError as error:
            msg = f"domain result address {result_address!r} is not in this mapping"
            raise KeyError(msg) from error

    def result_for(
        self,
        point: DomainPointRef,
        product_use: DomainProductUseRef,
    ) -> DomainMappedResult[EntryAddressT, ResultAddressT]:
        """Return the result supplying one exact context-owned logical output."""

        try:
            return self.result_by_output_identity[(id(point), id(product_use))]
        except KeyError as error:
            msg = (
                "logical output is not in this result mapping: "
                f"point={point.id!r}, product_use={product_use.id!r}"
            )
            raise KeyError(msg) from error


@dataclass(frozen=True, slots=True)
class DomainMeasurementPlan[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
]:
    """Context-bound source and host-transform ownership for one invocation."""

    context: DomainBatchContext
    mapping: DomainResultMapping[EntryAddressT, ResultAddressT]
    source_product_uses: tuple[DomainProductUseRef, ...]
    derived_product_uses: tuple[DomainProductUseRef, ...]
    product_uses: tuple[DomainProductUseRef, ...]
    host_transforms: tuple[DomainHostTransformBinding, ...]
    source_fragment: BoundDomainMeasurementValueFragment[
        EntryAddressT,
        ResultAddressT,
    ] = field(repr=False)
    transforms: BoundHostMeasurementTransformPlan | None = field(
        default=None,
        repr=False,
    )


class DomainPreparationBuilder:
    """Context-bound constructor for one complete prepared execution proof.

    Result mapping, value ownership, host transforms, invocation identity, and
    result decoding are all lowered behind this facade. Laboratory adapters
    provide only SDK references and target-owned payloads.
    """

    __slots__ = ("_context",)

    def __init__(self, context: DomainBatchContext) -> None:
        self._context = context

    @property
    def context(self) -> DomainBatchContext:
        return self._context

    def map_measurements[
        EntryAddressT: Hashable,
        ResultAddressT: Hashable,
    ](
        self,
        *,
        entries: Sequence[DomainTargetEntry[EntryAddressT, ResultAddressT]],
        entry_points: Sequence[DomainEntryPointBinding[EntryAddressT]],
        results: Sequence[DomainResultUseBinding[EntryAddressT, ResultAddressT]],
    ) -> DomainResultMapping[EntryAddressT, ResultAddressT]:
        """Close exact direct-result coverage for the current selected batch."""

        selected_entries = tuple(entries)
        selected_entry_points = tuple(entry_points)
        selected_results = tuple(results)

        context = self._context
        point_ids = {id(point) for point in context.points}
        if any(id(binding.point) not in point_ids for binding in selected_entry_points):
            msg = "domain entry binding references a point outside this batch context"
            raise ValueError(msg)
        direct_use_ids = {
            id(product_use) for product_use in context.direct_product_uses
        }
        if any(
            id(binding.product_use) not in direct_use_ids
            for binding in selected_results
        ):
            msg = "domain result binding references a non-direct or foreign product use"
            raise ValueError(msg)

        native = seal_domain_result_mapping(
            context.linked_points,
            tuple(
                product_use_id(product_use)
                for product_use in context.direct_product_uses
            ),
            tuple(
                AdapterEntryResults(entry.entry_address, entry.result_addresses)
                for entry in selected_entries
            ),
            tuple(
                EntryPointBinding(
                    binding.entry_address,
                    point_id(binding.point),
                )
                for binding in selected_entry_points
            ),
            tuple(
                ResultUseBinding(
                    binding.entry_address,
                    binding.result_address,
                    product_use_id(binding.product_use),
                )
                for binding in selected_results
            ),
        )
        return _result_mapping_from_native(
            context,
            context.direct_product_uses,
            selected_entries,
            native,
        )

    def measurement_plan[
        EntryAddressT: Hashable,
        ResultAddressT: Hashable,
    ](
        self,
        mapping: DomainResultMapping[EntryAddressT, ResultAddressT],
        *,
        host_transforms: Sequence[DomainHostTransformBinding] = (),
    ) -> DomainMeasurementPlan[EntryAddressT, ResultAddressT]:
        """Compile exact direct and host-derived value ownership before effects."""

        context = self._context
        if mapping.context is not context:
            msg = "domain measurement mapping belongs to another batch context"
            raise ValueError(msg)
        if not _same_refs(mapping.product_uses, context.direct_product_uses):
            msg = "domain measurement mapping changed direct product ownership"
            raise ValueError(msg)
        supplied_bindings = tuple(host_transforms)

        authored_identity = {
            id(transform): transform for transform in context.measurement_transforms
        }
        if any(
            id(binding.transform) not in authored_identity
            for binding in supplied_bindings
        ):
            msg = (
                "domain host bindings must reference transforms authored in "
                "this batch context"
            )
            raise ValueError(msg)
        binding_by_transform = {
            id(binding.transform): binding for binding in supplied_bindings
        }
        if len(binding_by_transform) != len(supplied_bindings):
            msg = "domain host transform bindings must be unique"
            raise ValueError(msg)
        if set(binding_by_transform) != set(authored_identity):
            msg = "domain host bindings must exactly cover authored transforms"
            raise ValueError(msg)
        selected_bindings = tuple(
            binding_by_transform[id(transform)]
            for transform in context.measurement_transforms
        )

        native_pairs = tuple(
            lower_domain_host_transform_binding(context, binding)
            for binding in selected_bindings
        )
        native_transforms = tuple(transform for transform, _ in native_pairs)
        linked_points = context.linked_points
        source_fragment_id = "scopecat.domain/source"
        transform_fragment_ids = tuple(
            f"scopecat.domain/transform/{transform.id.value}"
            for transform in native_transforms
        )
        product_use_ids = tuple(
            product_use_id(product_use) for product_use in context.product_uses
        )
        value_assembly = select_measurement_value_assembly(
            linked_points,
            required_product_use_ids=product_use_ids,
            fragment_defs=(
                ProductValueFragmentDef(
                    source_fragment_id,
                    tuple(
                        product_use_id(product_use)
                        for product_use in context.direct_product_uses
                    ),
                ),
                *(
                    ProductValueFragmentDef(
                        fragment_id,
                        tuple(
                            product_use_id(product_use)
                            for port in binding.transform.outputs
                            for product_use in port.product_uses
                        ),
                    )
                    for fragment_id, binding in zip(
                        transform_fragment_ids,
                        selected_bindings,
                        strict=True,
                    )
                ),
            ),
        )
        source_fragment = bind_domain_output_fragment(
            value_assembly,
            source_fragment_id,
            SelectedDomainMeasurementOutputs(mapping.native),
        )
        transforms: BoundHostMeasurementTransformPlan | None = None
        if native_transforms:
            graph = verify_measurement_transform_graph(
                linked_points,
                native_transforms,
            )
            implementations = _native_host_implementations(native_pairs)
            selection = select_host_measurement_transforms(
                graph,
                implementations,
                tuple(
                    HostMeasurementTransformImplementationBinding(
                        transform.id,
                        implementation.id,
                    )
                    for transform, implementation in native_pairs
                ),
            )
            transforms = bind_host_measurement_transforms(
                selection,
                value_assembly,
                tuple(
                    HostMeasurementTransformFragmentBinding(
                        transform.id,
                        fragment_id,
                    )
                    for transform, fragment_id in zip(
                        native_transforms,
                        transform_fragment_ids,
                        strict=True,
                    )
                ),
            )

        return DomainMeasurementPlan(
            context=context,
            mapping=mapping,
            source_product_uses=context.direct_product_uses,
            derived_product_uses=context.derived_product_uses,
            product_uses=context.product_uses,
            host_transforms=selected_bindings,
            source_fragment=source_fragment,
            transforms=transforms,
        )

    def build[
        EntryAddressT: Hashable,
        ResultAddressT: Hashable,
        PayloadT,
        ResultT,
    ](
        self,
        *,
        measurements: DomainMeasurementPlan[EntryAddressT, ResultAddressT],
        invocation: DomainInvocationSpec[PayloadT],
        runtime: DomainRuntime[PayloadT, ResultT],
        realize: Callable[
            [CorrelatedDomainFetch[ResultT]],
            Sequence[DomainResultValue[ResultAddressT]],
        ],
        resource_claims: Sequence[DomainResourceClaim] = (),
    ) -> PreparedDomainExecution:
        """Close one declarative target job behind the core execution ABI."""

        if measurements.context is not self._context:
            msg = "domain measurement plan belongs to another batch context"
            raise ValueError(msg)
        selected_claims = tuple(resource_claims)
        if len(selected_claims) != len(set(selected_claims)):
            msg = "domain execution resource claims must be unique"
            raise ValueError(msg)

        target = invocation.target
        native_mapping = measurements.mapping.native
        native_invocation = close_domain_invocation(
            native_mapping,
            invocation_id=invocation.invocation_id,
            target_id=target.target_id,
            compiler_id=target.compiler_id,
            capability_fingerprint=target.capability_fingerprint,
            artifact_id=target.artifact_id,
            artifact_fingerprint=target.artifact_fingerprint,
            adapter_intent=invocation.adapter_intent,
            payload=invocation.payload,
        )
        source_fragment = measurements.source_fragment
        native_outputs = source_fragment.domain_outputs

        def close_realized_values(
            fetched: CorrelatedDomainFetch[ResultT],
        ) -> ClosedDomainOutputValues[EntryAddressT, ResultAddressT]:
            candidates = tuple(realize(fetched))
            return seal_domain_output_values(
                native_outputs,
                tuple(
                    DomainOutputValue(candidate.result_address, candidate.value)
                    for candidate in candidates
                ),
            )

        return PreparedDomainExecution(
            adapter_id=self._context.adapter_id,
            context=self._context,
            invocation=cast("ErasedDomainInvocation", native_invocation),
            runtime=cast("ErasedDomainRuntime", runtime),
            realize=cast("ErasedDomainRealizer", close_realized_values),
            source_fragment=cast(
                "BoundDomainMeasurementValueFragment[Hashable, Hashable]",
                source_fragment,
            ),
            resource_claims=tuple(
                ExecutionResourceClaim(claim.kind, claim.id)
                for claim in selected_claims
            ),
            transforms=measurements.transforms,
        )


def _result_mapping_from_native[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
](
    context: DomainBatchContext,
    product_uses: tuple[DomainProductUseRef, ...],
    target_entries: tuple[DomainTargetEntry[EntryAddressT, ResultAddressT], ...],
    native: ClosedDomainResultMapping[EntryAddressT, ResultAddressT],
) -> DomainResultMapping[EntryAddressT, ResultAddressT]:
    point_refs_by_id = {point_id(point): point for point in context.points}
    product_use_refs_by_id = {
        product_use_id(product_use): product_use for product_use in product_uses
    }
    mapped_results: list[DomainMappedResult[EntryAddressT, ResultAddressT]] = []
    mapped_results_by_native_identity: dict[
        int,
        DomainMappedResult[EntryAddressT, ResultAddressT],
    ] = {}
    for native_result in native.results:
        mapped_result = DomainMappedResult(
            entry_address=native_result.entry_address,
            result_address=native_result.result_address,
            point=point_refs_by_id[native_result.logical_point_id],
            product_uses=tuple(
                product_use_refs_by_id[product_use_id]
                for product_use_id in native_result.product_use_ids
            ),
        )
        mapped_results.append(mapped_result)
        mapped_results_by_native_identity[id(native_result)] = mapped_result

    mapped_entries: list[DomainMappedEntry[EntryAddressT, ResultAddressT]] = []
    for native_entry in native.entries:
        mapped_entry = DomainMappedEntry(
            entry_address=native_entry.entry_address,
            point=point_refs_by_id[native_entry.logical_point_id],
            results=tuple(
                mapped_results_by_native_identity[id(native_result)]
                for native_result in native_entry.results
            ),
        )
        mapped_entries.append(mapped_entry)

    selected_results = tuple(mapped_results)
    return DomainResultMapping(
        context=context,
        product_uses=product_uses,
        target_entries=target_entries,
        entries=tuple(mapped_entries),
        results=selected_results,
        result_by_address=MappingProxyType(
            {result.result_address: result for result in selected_results}
        ),
        result_by_output_identity=MappingProxyType(
            {
                (id(result.point), id(product_use)): result
                for result in selected_results
                for product_use in result.product_uses
            }
        ),
        native=native,
    )


def _same_refs(
    selected: tuple[DomainProductUseRef, ...],
    expected: tuple[DomainProductUseRef, ...],
) -> bool:
    return len(selected) == len(expected) and all(
        candidate is owned for candidate, owned in zip(selected, expected, strict=True)
    )


def _native_host_implementations(
    pairs: tuple[
        tuple[MeasurementTransformDef, HostMeasurementTransformImplementation],
        ...,
    ],
) -> tuple[HostMeasurementTransformImplementation, ...]:
    grouped: dict[
        str,
        list[tuple[MeasurementTransformDef, HostMeasurementTransformImplementation]],
    ] = {}
    for pair in pairs:
        grouped.setdefault(pair[1].id, []).append(pair)
    return tuple(_host_implementation_dispatcher(group) for group in grouped.values())


def _host_implementation_dispatcher(
    group: list[tuple[MeasurementTransformDef, HostMeasurementTransformImplementation]],
) -> HostMeasurementTransformImplementation:
    first = group[0][1]
    contract = (
        first.semantic_id,
        first.semantic_version,
        first.rate,
        first.implementation_fingerprint,
    )
    if any(
        (
            implementation.semantic_id,
            implementation.semantic_version,
            implementation.rate,
            implementation.implementation_fingerprint,
        )
        != contract
        for _, implementation in group[1:]
    ):
        msg = f"domain host implementation id {first.id!r} has conflicting contracts"
        raise ValueError(msg)
    by_transform = {transform.id: implementation for transform, implementation in group}
    if len(by_transform) != len(group):
        msg = "domain measurement transform ids must be unique"
        raise ValueError(msg)

    def validate(transform: MeasurementTransformDef) -> None:
        try:
            implementation = by_transform[transform.id]
        except KeyError as error:
            msg = "domain host validator received an unbound transform"
            raise ValueError(msg) from error
        implementation.validate_transform(transform)

    def kernel(
        call: HostMeasurementTransformCall,
    ) -> Mapping[str, MeasurementValue]:
        try:
            implementation = by_transform[call.transform_id]
        except KeyError as error:
            msg = "domain host kernel received an unbound transform call"
            raise ValueError(msg) from error
        return implementation.kernel(call)

    return HostMeasurementTransformImplementation(
        id=first.id,
        semantic_id=first.semantic_id,
        semantic_version=first.semantic_version,
        rate=first.rate,
        implementation_fingerprint=first.implementation_fingerprint,
        validate_transform=validate,
        kernel=kernel,
    )


__all__ = [
    "DomainEntryPointBinding",
    "DomainMappedEntry",
    "DomainMappedResult",
    "DomainMeasurementPlan",
    "DomainPreparationBuilder",
    "DomainResultMapping",
    "DomainResultUseBinding",
    "DomainTargetEntry",
]

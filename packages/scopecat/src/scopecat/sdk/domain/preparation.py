"""Builder facade for closing one selected domain batch before effects."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from scopecat.compiler.typed.products import ProductDef
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.point_identity import LogicalPointId
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.measurements.host_transforms import (
    HostMeasurementTransformPlan,
    bind_host_measurement_transforms,
)
from scopecat.measurements.values import (
    MeasurementValueCandidate,
)
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
    DomainOutputValue,
    close_domain_invocation,
    seal_domain_output_values,
)
from scopecat.sdk.domain.job import (
    DomainInvocationSpec,
    DomainResultValue,
)
from scopecat.sdk.domain.measurements import DomainHostTransformBinding
from scopecat.sdk.domain.runtime import CorrelatedDomainFetch, DomainRuntime
from scopecat.sdk.domain.view import DomainPointRef, DomainProductUseRef


@dataclass(frozen=True, slots=True)
class DomainResultBinding[ResultAddressT: Hashable]:
    """Opaque target result location bound to one logical product occurrence."""

    result_address: ResultAddressT
    point: DomainPointRef
    product_use: DomainProductUseRef


@dataclass(frozen=True, slots=True)
class DomainMappedResult[ResultAddressT: Hashable]:
    """One opaque result location and its exact logical output ownership."""

    result_address: ResultAddressT
    point: DomainPointRef
    product_uses: tuple[DomainProductUseRef, ...]
    product: ProductDef = field(repr=False)

    @property
    def logical_point_id(self) -> LogicalPointId:
        return point_id(self.point)

    @property
    def product_use_ids(self) -> tuple[ProductUseId, ...]:
        return tuple(product_use_id(use) for use in self.product_uses)

    @property
    def product_id(self) -> ProductId:
        return self.product.id


@dataclass(frozen=True, slots=True)
class DomainResultMapping[
    ResultAddressT: Hashable,
]:
    """Exact inventory from opaque result locations to SDK-owned references.

    ``results`` follows canonical logical-point and product-use order. All point
    and product-use values are the exact references assembled for the
    preparation context; physical entry structure remains adapter-owned.
    """

    context: DomainBatchContext
    selected_product_uses: tuple[ProductUse, ...] = field(repr=False)
    results: tuple[DomainMappedResult[ResultAddressT], ...]
    product_by_use_id: Mapping[ProductUseId, ProductDef] = field(
        repr=False, compare=False
    )
    _contract_fingerprint: str = field(repr=False, compare=False)

    @property
    def contract_fingerprint(self) -> str:
        return self._contract_fingerprint

    def product_for_use(self, product_use_id: ProductUseId) -> ProductDef:
        try:
            return self.product_by_use_id[product_use_id]
        except KeyError as error:
            raise KeyError(product_use_id.value) from error


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
        ResultAddressT: Hashable,
    ](
        self,
        *,
        results: Sequence[DomainResultBinding[ResultAddressT]],
    ) -> DomainResultMapping[ResultAddressT]:
        """Close exact direct-result coverage for the current selected batch."""

        selected_results = tuple(results)

        context = self._context
        point_ids = {id(point) for point in context.points}
        if any(id(binding.point) not in point_ids for binding in selected_results):
            msg = "domain result binding references a point outside this batch context"
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

        return _close_result_mapping(
            context,
            selected_results,
        )

    def build[
        ResultAddressT: Hashable,
        PayloadT,
        ResultT,
    ](
        self,
        *,
        mapping: DomainResultMapping[ResultAddressT],
        host_transforms: Sequence[DomainHostTransformBinding] = (),
        invocation: DomainInvocationSpec[PayloadT],
        runtime: DomainRuntime[PayloadT, ResultT],
        realize: Callable[
            [CorrelatedDomainFetch[ResultT]],
            Sequence[DomainResultValue[ResultAddressT]],
        ],
    ) -> PreparedDomainExecution:
        """Close one declarative target job behind the core execution ABI."""

        if mapping.context is not self._context:
            msg = "domain result mapping belongs to another batch context"
            raise ValueError(msg)
        target = invocation.target
        native_invocation = close_domain_invocation(
            mapping,
            invocation_id=invocation.invocation_id,
            target_id=target.target_id,
            compiler_id=target.compiler_id,
            capability_fingerprint=target.capability_fingerprint,
            artifact_id=target.artifact_id,
            artifact_fingerprint=target.artifact_fingerprint,
            target_intent=invocation.target_intent,
            payload=invocation.payload,
        )

        def close_realized_values(
            fetched: CorrelatedDomainFetch[ResultT],
        ) -> tuple[MeasurementValueCandidate, ...]:
            candidates = tuple(realize(fetched))
            return seal_domain_output_values(
                mapping,
                tuple(
                    DomainOutputValue(candidate.result_address, candidate.value)
                    for candidate in candidates
                ),
            )

        return PreparedDomainExecution(
            invocation=cast("ErasedDomainInvocation", native_invocation),
            runtime=cast("ErasedDomainRuntime", runtime),
            realize=cast("ErasedDomainRealizer", close_realized_values),
            points=self._context.run_points,
            transforms=_bind_host_transforms(
                self._context,
                tuple(host_transforms),
            ),
        )


def _bind_host_transforms(
    context: DomainBatchContext,
    supplied_bindings: tuple[DomainHostTransformBinding, ...],
) -> HostMeasurementTransformPlan | None:
    authored = {
        id(transform): transform for transform in context.measurement_transforms
    }
    if any(id(binding.transform) not in authored for binding in supplied_bindings):
        raise ValueError("domain host binding references a foreign transform")
    binding_by_transform = {
        id(binding.transform): binding for binding in supplied_bindings
    }
    if len(binding_by_transform) != len(supplied_bindings):
        raise ValueError("domain host transform bindings must be unique")
    if set(binding_by_transform) != set(authored):
        raise ValueError("domain host bindings must exactly cover residual transforms")
    # The context preserves compiler topology; adapter submission order is irrelevant.
    selected = tuple(
        binding_by_transform[id(transform)]
        for transform in context.measurement_transforms
    )
    native_pairs = tuple(
        lower_domain_host_transform_binding(context, binding) for binding in selected
    )
    if not native_pairs:
        return None
    return bind_host_measurement_transforms(
        native_pairs,
        tuple(product_use_id(use) for use in context.direct_product_uses),
    )


def _close_result_mapping[
    ResultAddressT: Hashable,
](
    context: DomainBatchContext,
    result_bindings: tuple[DomainResultBinding[ResultAddressT], ...],
) -> DomainResultMapping[ResultAddressT]:
    use_refs = context.direct_product_uses
    use_ref_by_id = {product_use_id(use): use for use in use_refs}
    use_order = {use_id: index for index, use_id in enumerate(use_ref_by_id)}
    point_order = {id(point): index for index, point in enumerate(context.points)}
    bindings_by_result: dict[
        ResultAddressT,
        list[DomainResultBinding[ResultAddressT]],
    ] = {}
    output_owners: dict[tuple[int, ProductUseId], ResultAddressT] = {}
    for binding in result_bindings:
        use_id = product_use_id(binding.product_use)
        if use_ref_by_id.get(use_id) is not binding.product_use:
            raise ValueError("domain result binding references a foreign product use")
        output = (id(binding.point), use_id)
        if output in output_owners:
            raise ValueError(
                "domain result bindings require unique point/product-use outputs"
            )
        output_owners[output] = binding.result_address
        bindings_by_result.setdefault(binding.result_address, []).append(binding)

    expected_outputs = {
        (id(point), use_id) for point in context.points for use_id in use_ref_by_id
    }
    if set(output_owners) != expected_outputs:
        raise ValueError(
            "domain result bindings must exactly cover every logical output"
        )

    catalog = context.measurement_catalog
    core_use_by_id = {use.id: use for use in catalog.product_uses}
    product_by_id = {product.id: product for product in catalog.product_defs}
    product_by_use_id = {
        use_id: product_by_id[core_use_by_id[use_id].product_id]
        for use_id in use_ref_by_id
    }
    address_by_logical_product: dict[
        tuple[int, ProductId],
        ResultAddressT,
    ] = {}
    for binding in result_bindings:
        use_id = product_use_id(binding.product_use)
        output = (id(binding.point), product_by_use_id[use_id].id)
        previous = address_by_logical_product.setdefault(
            output,
            binding.result_address,
        )
        if previous != binding.result_address:
            raise ValueError(
                "one logical product result cannot be split across locations"
            )
    mapped_results: list[DomainMappedResult[ResultAddressT]] = []
    for result_address, bindings in bindings_by_result.items():
        points = {id(binding.point): binding.point for binding in bindings}
        if len(points) != 1:
            raise ValueError(
                "one domain result location may supply only one logical point"
            )
        point = next(iter(points.values()))
        use_ids = tuple(
            use_id
            for use_id in use_ref_by_id
            if any(
                product_use_id(binding.product_use) == use_id for binding in bindings
            )
        )
        product_ids = {product_by_use_id[use_id].id for use_id in use_ids}
        if len(product_ids) != 1:
            raise ValueError(
                "one domain result may fan out only within one logical product"
            )
        mapped_results.append(
            DomainMappedResult(
                result_address=result_address,
                point=point,
                product_uses=tuple(use_ref_by_id[use_id] for use_id in use_ids),
                product=product_by_use_id[use_ids[0]],
            )
        )

    mapped_results.sort(
        key=lambda result: (
            point_order[id(result.point)],
            min(use_order[use_id] for use_id in result.product_use_ids),
        )
    )

    selected_results = tuple(mapped_results)
    selected_use_ids = tuple(use_ref_by_id)
    selected_core_uses = tuple(core_use_by_id[use_id] for use_id in selected_use_ids)
    fingerprint = stable_content_hash(
        content_fingerprint(
            {
                "schema": "scopecat.domain_result_contract.v5",
                "selected_product_uses": [
                    {
                        "product_use_id": use.id.value,
                        "product": product_by_use_id[use.id],
                    }
                    for use in selected_core_uses
                ],
                "results": [
                    {
                        "result_address": result.result_address,
                        "logical_point_id": result.logical_point_id.value,
                        "product_use_ids": [
                            use_id.value for use_id in result.product_use_ids
                        ],
                        "product": result.product,
                    }
                    for result in selected_results
                ],
            }
        )
    )
    return DomainResultMapping(
        context=context,
        selected_product_uses=selected_core_uses,
        results=selected_results,
        product_by_use_id=MappingProxyType(
            {use_id: product_by_use_id[use_id] for use_id in selected_use_ids}
        ),
        _contract_fingerprint=fingerprint,
    )

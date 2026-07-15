"""SDK-owned selection and preparation context for domain adapters.

Compiler-owned materialized plans enter only through the private projection
bridge at the bottom of this module.  Public adapters inspect immutable views,
return a declarative offer, and prepare one exact call through a context whose
references are already scoped to the selected batch.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast, override

from scopecat.compiler.linking.linked import (
    MaterializedLinkedPointBatch,
    MaterializedLinkedPoints,
    MaterializedLinkedPointSet,
)
from scopecat.compiler.semantic.model import DomainCallId
from scopecat.compiler.typed.point_domain import LogicalPointId
from scopecat.compiler.typed.products import ProductDef
from scopecat.kernel.product_identity import ProductId, ProductUseId
from scopecat.planning.domain_placement import (
    DomainCallExecutionSlice,
    domain_call_execution_slices,
)
from scopecat.sdk.domain.view import (
    DomainBatchView,
    DomainCallPointView,
    DomainCallView,
    DomainInputPortView,
    DomainMeasurementTransform,
    DomainPointRef,
    DomainProductAxisView,
    DomainProductContractView,
    DomainProductUseRef,
    DomainProgramView,
    DomainResultBindingView,
    DomainResultPortView,
    domain_measurement_transform_internal,
    domain_point_native_internal,
    domain_point_ref_internal,
    domain_product_use_native_internal,
    domain_product_use_ref_internal,
    domain_transform_input_port_internal,
    domain_transform_output_port_internal,
)

if TYPE_CHECKING:
    from scopecat.sdk.domain.preparation import DomainPreparationBuilder


@dataclass(frozen=True, slots=True, init=False)
class DomainExecutionOffer:
    """One adapter's declarative offer for exactly one authored domain call.

    Every authored domain-call result is a direct target result.  Core derives
    the call's downstream measurement-transform and product coverage from the
    typed producer graph; the adapter only identifies the call and its stable
    batch capacity.
    """

    call_id: str
    max_points_per_batch: int

    @classmethod
    def for_call(
        cls,
        call: DomainCallView,
        *,
        max_points_per_batch: int = 1,
    ) -> DomainExecutionOffer:
        if max_points_per_batch <= 0:
            msg = "domain max_points_per_batch must be positive"
            raise ValueError(msg)
        selected = object.__new__(cls)
        object.__setattr__(selected, "call_id", call.id)
        object.__setattr__(
            selected,
            "max_points_per_batch",
            max_points_per_batch,
        )
        return selected


class DomainBatchContext(ABC):
    """Backend-selected batch for one already accepted adapter offer."""

    __slots__ = ()

    @property
    @abstractmethod
    def batch_ordinal(self) -> int: ...

    @property
    @abstractmethod
    def call(self) -> DomainCallView: ...

    @property
    @abstractmethod
    def points(self) -> tuple[DomainPointRef, ...]: ...

    @property
    @abstractmethod
    def product_uses(self) -> tuple[DomainProductUseRef, ...]: ...

    @property
    @abstractmethod
    def direct_product_uses(self) -> tuple[DomainProductUseRef, ...]: ...

    @property
    @abstractmethod
    def derived_product_uses(self) -> tuple[DomainProductUseRef, ...]: ...

    @property
    @abstractmethod
    def measurement_transforms(self) -> tuple[DomainMeasurementTransform, ...]: ...

    def new_preparation(self) -> DomainPreparationBuilder:
        """Create the one SDK builder that may close this batch for execution."""

        from scopecat.sdk.domain.preparation import (
            domain_preparation_builder_for_context_internal,
        )

        return domain_preparation_builder_for_context_internal(self)


class _DomainBatchContext(DomainBatchContext):
    __slots__ = (
        "_adapter_id",
        "_batch_ordinal",
        "_call",
        "_derived_product_uses",
        "_direct_product_uses",
        "_linked_points",
        "_measurement_transforms",
        "_points",
        "_product_uses",
    )

    def __init__(
        self,
        *,
        batch_ordinal: int,
        call: DomainCallView,
        points: tuple[DomainPointRef, ...],
        product_uses: tuple[DomainProductUseRef, ...],
        direct_product_uses: tuple[DomainProductUseRef, ...],
        derived_product_uses: tuple[DomainProductUseRef, ...],
        measurement_transforms: tuple[DomainMeasurementTransform, ...],
        linked_points: MaterializedLinkedPointBatch,
        adapter_id: str,
    ) -> None:
        self._batch_ordinal = batch_ordinal
        self._call = call
        self._points = points
        self._product_uses = product_uses
        self._direct_product_uses = direct_product_uses
        self._derived_product_uses = derived_product_uses
        self._measurement_transforms = measurement_transforms
        self._linked_points = linked_points
        self._adapter_id = adapter_id

    @property
    @override
    def batch_ordinal(self) -> int:
        return self._batch_ordinal

    @property
    @override
    def call(self) -> DomainCallView:
        return self._call

    @property
    @override
    def points(self) -> tuple[DomainPointRef, ...]:
        return self._points

    @property
    @override
    def product_uses(self) -> tuple[DomainProductUseRef, ...]:
        return self._product_uses

    @property
    @override
    def direct_product_uses(self) -> tuple[DomainProductUseRef, ...]:
        return self._direct_product_uses

    @property
    @override
    def derived_product_uses(self) -> tuple[DomainProductUseRef, ...]:
        return self._derived_product_uses

    @property
    @override
    def measurement_transforms(self) -> tuple[DomainMeasurementTransform, ...]:
        return self._measurement_transforms


@dataclass(frozen=True, slots=True)
class DomainPlanProjectionInternal:
    linked_points: MaterializedLinkedPoints = field(repr=False)
    point_refs: tuple[DomainPointRef, ...]
    product_use_refs: tuple[DomainProductUseRef, ...]
    _point_refs_by_id: dict[LogicalPointId, DomainPointRef] = field(
        repr=False,
        compare=False,
    )
    _product_use_refs_by_id: dict[ProductUseId, DomainProductUseRef] = field(
        repr=False,
        compare=False,
    )
    _product_contracts: dict[ProductId, DomainProductContractView] = field(
        repr=False,
        compare=False,
    )
    _measurement_transforms_by_call: dict[
        DomainCallId,
        tuple[DomainMeasurementTransform, ...],
    ] = field(repr=False, compare=False)
    _execution_slices_by_call: dict[DomainCallId, DomainCallExecutionSlice] = field(
        repr=False,
        compare=False,
    )

    def view(self, selected: MaterializedLinkedPointSet) -> DomainBatchView:
        self._require_owned_points(selected)
        points = tuple(
            self._point_refs_by_id[point.logical_id]
            for point in selected.point_domain.points
        )
        return DomainBatchView(
            calls=tuple(
                DomainCallView(
                    id=materialized.call.id.qualified_name,
                    program=DomainProgramView(
                        id=materialized.program.id.qualified_name,
                        dialect_id=materialized.program.dialect_id,
                        dialect_version=materialized.program.dialect_version,
                        body=materialized.program.body,
                        inputs=tuple(
                            DomainInputPortView(port.id, port.value_type)
                            for port in materialized.program.input_ports
                        ),
                        results=tuple(
                            DomainResultPortView(port.id, port.contract)
                            for port in materialized.program.result_ports
                        ),
                    ),
                    points=tuple(
                        DomainCallPointView(
                            ref=self._point_refs_by_id[point.logical_id],
                            inputs=point.inputs,
                        )
                        for point in materialized.points
                    ),
                    results=tuple(
                        DomainResultBindingView(
                            id=result.id,
                            product=self._product_contracts[result.product_id],
                            product_uses=tuple(
                                self._product_use_refs_by_id[use_id]
                                for use_id in result.product_use_ids
                            ),
                            contract=next(
                                port.contract
                                for port in materialized.program.result_ports
                                if port.id == result.id
                            ),
                        )
                        for result in materialized.call.results
                    ),
                    measurement_transforms=self._measurement_transforms_by_call.get(
                        materialized.call.id,
                        (),
                    ),
                )
                for materialized in selected.domain_calls
            ),
            points=points,
            product_uses=self.product_use_refs,
        )

    def _require_owned_points(self, selected: MaterializedLinkedPointSet) -> None:
        if selected is self.linked_points:
            return
        if (
            isinstance(selected, MaterializedLinkedPointBatch)
            and selected.parent is self.linked_points
        ):
            return
        msg = "domain view projection requires points from its materialized plan"
        raise ValueError(msg)

    def execution_slice(self, call: DomainCallView) -> DomainCallExecutionSlice:
        selected = tuple(
            execution_slice
            for call_id, execution_slice in self._execution_slices_by_call.items()
            if call_id.qualified_name == call.id
        )
        if len(selected) != 1:
            msg = f"domain call {call.id!r} has no unique execution slice"
            raise ValueError(msg)
        return selected[0]


def project_domain_plan_internal(
    linked_points: MaterializedLinkedPoints,
) -> DomainPlanProjectionInternal:
    product_contracts = {
        product.id: _product_contract_view(product)
        for product in linked_points.linked_plan.product_defs
    }
    point_refs = tuple(
        domain_point_ref_internal(
            ref_id=point.logical_id.value,
            ordinal=point.logical_ordinal,
            native=point.logical_id,
        )
        for point in linked_points.point_domain.points
    )
    point_refs_by_id = {
        cast("LogicalPointId", domain_point_native_internal(ref)): ref
        for ref in point_refs
    }
    product_use_refs = tuple(
        domain_product_use_ref_internal(
            ref_id=use.id.value,
            product=product_contracts[use.product_id],
            native=use.id,
        )
        for use in linked_points.linked_plan.product_uses
    )
    product_use_refs_by_id = {
        cast("ProductUseId", domain_product_use_native_internal(ref)): ref
        for ref in product_use_refs
    }
    transform_refs = {
        transform.id: domain_measurement_transform_internal(
            transform_id=transform.id.qualified_name,
            semantic=transform.semantic,
            inputs=tuple(
                domain_transform_input_port_internal(
                    port_id=port.id,
                    product_use=product_use_refs_by_id[port.product_use_id],
                    product=product_contracts[port.product_id],
                )
                for port in transform.inputs
            ),
            outputs=tuple(
                domain_transform_output_port_internal(
                    port_id=port.id,
                    product=product_contracts[port.product_id],
                    product_uses=tuple(
                        product_use_refs_by_id[use_id]
                        for use_id in port.product_use_ids
                    ),
                )
                for port in transform.outputs
            ),
        )
        for transform in linked_points.linked_plan.program.measurement_transforms
    }
    execution_slices = domain_call_execution_slices(linked_points.linked_plan.program)
    execution_slices_by_call = {
        execution_slice.call_id: execution_slice for execution_slice in execution_slices
    }
    transforms_by_call = {
        execution_slice.call_id: tuple(
            transform_refs[transform.id] for transform in execution_slice.transforms
        )
        for execution_slice in execution_slices
    }
    return DomainPlanProjectionInternal(
        linked_points=linked_points,
        point_refs=point_refs,
        product_use_refs=product_use_refs,
        _point_refs_by_id=point_refs_by_id,
        _product_use_refs_by_id=product_use_refs_by_id,
        _product_contracts=product_contracts,
        _measurement_transforms_by_call=transforms_by_call,
        _execution_slices_by_call=execution_slices_by_call,
    )


def make_domain_batch_context_internal(
    projection: DomainPlanProjectionInternal,
    batch: MaterializedLinkedPointBatch,
    offer: DomainExecutionOffer,
    *,
    adapter_id: str,
    batch_ordinal: int,
) -> DomainBatchContext:
    view = projection.view(batch)
    call = offered_call_internal(view, offer)
    execution_slice = execution_slice_for_call_internal(projection, call)
    owned_ids = set(execution_slice.product_use_ids)
    direct_ids = set(execution_slice.direct_product_use_ids)
    derived_ids = set(execution_slice.derived_product_use_ids)
    owned = tuple(
        product_use
        for product_use in view.product_uses
        if product_use_id_internal(product_use) in owned_ids
    )
    direct = tuple(
        product_use
        for product_use in view.product_uses
        if product_use_id_internal(product_use) in direct_ids
    )
    derived = tuple(
        product_use
        for product_use in view.product_uses
        if product_use_id_internal(product_use) in derived_ids
    )
    return _DomainBatchContext(
        batch_ordinal=batch_ordinal,
        call=call,
        points=view.points,
        product_uses=owned,
        direct_product_uses=direct,
        derived_product_uses=derived,
        measurement_transforms=call.measurement_transforms,
        linked_points=batch,
        adapter_id=adapter_id,
    )


def offered_call_internal(
    view: DomainBatchView,
    offer: DomainExecutionOffer,
) -> DomainCallView:
    selected = tuple(call for call in view.calls if call.id == offer.call_id)
    if len(selected) != 1:
        msg = (
            f"domain execution offer call {offer.call_id!r} does not identify "
            "exactly one call in this plan"
        )
        raise ValueError(msg)
    return selected[0]


def execution_slice_for_call_internal(
    projection: DomainPlanProjectionInternal,
    call: DomainCallView,
) -> DomainCallExecutionSlice:
    return projection.execution_slice(call)


def context_linked_points_internal(
    context: DomainBatchContext,
) -> MaterializedLinkedPointBatch:
    return cast(
        "MaterializedLinkedPointBatch",
        object.__getattribute__(context, "_linked_points"),
    )


def context_adapter_id_internal(context: DomainBatchContext) -> str:
    return cast("str", object.__getattribute__(context, "_adapter_id"))


def point_id_internal(ref: DomainPointRef) -> LogicalPointId:
    return cast("LogicalPointId", domain_point_native_internal(ref))


def product_use_id_internal(ref: DomainProductUseRef) -> ProductUseId:
    return cast("ProductUseId", domain_product_use_native_internal(ref))


def _product_contract_view(product: ProductDef) -> DomainProductContractView:
    return DomainProductContractView(
        id=product.id.qualified_name,
        kind=product.kind,
        unit=product.unit,
        dtype=product.dtype,
        axes=tuple(
            DomainProductAxisView(
                id=axis.id,
                kind=axis.kind,
                size=axis.size,
                unit=axis.unit,
                metadata=axis.metadata,
            )
            for axis in product.axes
        ),
        metadata=product.metadata,
    )


__all__ = [
    "DomainBatchContext",
    "DomainExecutionOffer",
]

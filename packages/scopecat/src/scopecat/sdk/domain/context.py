"""Public selection and preparation context for domain adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from scopecat.sdk.domain.view import (
    DomainCallView,
    DomainMeasurementTransform,
    DomainPointRef,
    DomainProductUseRef,
)

if TYPE_CHECKING:
    from scopecat.compiler.linking.linked import MaterializedLinkedPointBatch
    from scopecat.sdk.domain.preparation import DomainPreparationBuilder


@dataclass(frozen=True, slots=True)
class DomainExecutionOffer:
    """One adapter's declarative offer for exactly one authored domain call."""

    call_id: str
    max_points_per_batch: int

    def __post_init__(self) -> None:
        if not self.call_id:
            msg = "domain call id must be non-empty"
            raise ValueError(msg)
        if self.max_points_per_batch <= 0:
            msg = "domain max_points_per_batch must be positive"
            raise ValueError(msg)

    @classmethod
    def for_call(
        cls,
        call: DomainCallView,
        *,
        max_points_per_batch: int = 1,
    ) -> DomainExecutionOffer:
        return cls(
            call_id=call.id,
            max_points_per_batch=max_points_per_batch,
        )


@dataclass(frozen=True, slots=True)
class DomainBatchContext:
    """Backend-selected batch for one already accepted adapter offer."""

    batch_ordinal: int
    call: DomainCallView
    points: tuple[DomainPointRef, ...]
    product_uses: tuple[DomainProductUseRef, ...]
    direct_product_uses: tuple[DomainProductUseRef, ...]
    derived_product_uses: tuple[DomainProductUseRef, ...]
    measurement_transforms: tuple[DomainMeasurementTransform, ...]
    linked_points: MaterializedLinkedPointBatch = field(repr=False)
    adapter_id: str

    def new_preparation(self) -> DomainPreparationBuilder:
        """Create a builder that closes this batch for execution."""

        from scopecat.sdk.domain.preparation import DomainPreparationBuilder

        return DomainPreparationBuilder(self)


__all__ = [
    "DomainBatchContext",
    "DomainExecutionOffer",
]

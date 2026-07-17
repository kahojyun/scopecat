"""Public selection and preparation context for domain adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from scopecat.sdk.domain.view import (
    DomainExecutionView,
    DomainMeasurementTransform,
    DomainPointRef,
    DomainProductUseRef,
)

if TYPE_CHECKING:
    from scopecat.compiler.linking.linked import MaterializedLinkedPointBatch
    from scopecat.sdk.domain.preparation import DomainPreparationBuilder


@dataclass(frozen=True, slots=True)
class DomainExecutionOffer:
    """One adapter's declarative offer for the authored domain execution."""

    max_points_per_batch: int = 1

    def __post_init__(self) -> None:
        if self.max_points_per_batch <= 0:
            msg = "domain max_points_per_batch must be positive"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class DomainBatchContext:
    """Backend-selected batch for one already accepted adapter offer."""

    batch_ordinal: int
    execution: DomainExecutionView
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

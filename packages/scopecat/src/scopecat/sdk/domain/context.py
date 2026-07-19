"""Runtime preparation context for compiled domain jobs."""

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
class DomainBatchContext:
    """Runtime bindings for one pure compiled domain job."""

    batch_ordinal: int
    execution: DomainExecutionView
    points: tuple[DomainPointRef, ...]
    product_uses: tuple[DomainProductUseRef, ...]
    direct_product_uses: tuple[DomainProductUseRef, ...]
    derived_product_uses: tuple[DomainProductUseRef, ...]
    measurement_transforms: tuple[DomainMeasurementTransform, ...]
    linked_points: MaterializedLinkedPointBatch = field(repr=False)
    compiler_id: str

    def new_preparation(self) -> DomainPreparationBuilder:
        """Create a builder that closes this batch for execution."""

        from scopecat.sdk.domain.preparation import DomainPreparationBuilder

        return DomainPreparationBuilder(self)

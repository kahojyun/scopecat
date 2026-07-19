"""Runtime preparation context for compiled domain jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from scopecat.measurements.values import MeasurementValueCatalog
from scopecat.sdk.domain.view import (
    DomainExecutionView,
    DomainMeasurementTransform,
    DomainPointRef,
    DomainProductUseRef,
)

if TYPE_CHECKING:
    from scopecat.sdk.domain.preparation import DomainPreparationBuilder


@dataclass(frozen=True, slots=True)
class DomainBatchContext:
    """Runtime bindings for one pure compiled domain job."""

    batch_ordinal: int
    execution: DomainExecutionView
    product_uses: tuple[DomainProductUseRef, ...]
    direct_product_uses: tuple[DomainProductUseRef, ...]
    derived_product_uses: tuple[DomainProductUseRef, ...]
    measurement_catalog: MeasurementValueCatalog = field(repr=False)

    @property
    def points(self) -> tuple[DomainPointRef, ...]:
        """Return the canonical point references owned by the execution."""

        return tuple(point.ref for point in self.execution.points)

    @property
    def measurement_transforms(self) -> tuple[DomainMeasurementTransform, ...]:
        """Return the residual transforms owned by the execution."""

        return self.execution.measurement_transforms

    def new_preparation(self) -> DomainPreparationBuilder:
        """Create a builder that closes this batch for execution."""

        from scopecat.sdk.domain.preparation import DomainPreparationBuilder

        return DomainPreparationBuilder(self)

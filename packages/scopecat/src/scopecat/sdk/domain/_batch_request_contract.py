"""Import-cycle-free batch request contract for preparation internals."""

from __future__ import annotations

from typing import Protocol

from scopecat.measurements.points import RunPoint
from scopecat.measurements.values import MeasurementValueCatalog
from scopecat.sdk.domain.view import (
    DomainCallView,
    DomainPointRef,
    DomainProductUseRef,
)


class DomainBatchRequestView(Protocol):
    @property
    def batch_ordinal(self) -> int: ...

    @property
    def call(self) -> DomainCallView: ...

    @property
    def product_uses(self) -> tuple[DomainProductUseRef, ...]: ...

    @property
    def measurement_catalog(self) -> MeasurementValueCatalog: ...

    @property
    def run_points(self) -> tuple[RunPoint, ...]: ...

    @property
    def points(self) -> tuple[DomainPointRef, ...]: ...

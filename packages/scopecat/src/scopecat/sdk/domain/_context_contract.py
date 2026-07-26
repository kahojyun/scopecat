"""Structural context contract shared by domain preparation internals."""

from __future__ import annotations

from typing import Protocol

from scopecat.measurements.points import RunPoint
from scopecat.measurements.values import MeasurementValueCatalog
from scopecat.sdk.domain.view import (
    DomainExecutionView,
    DomainPointRef,
    DomainProductUseRef,
)


class DomainBatchContextView(Protocol):
    """Read-only batch data needed below the public context facade."""

    @property
    def batch_ordinal(self) -> int: ...

    @property
    def execution(self) -> DomainExecutionView: ...

    @property
    def product_uses(self) -> tuple[DomainProductUseRef, ...]: ...

    @property
    def measurement_catalog(self) -> MeasurementValueCatalog: ...

    @property
    def run_points(self) -> tuple[RunPoint, ...]: ...

    @property
    def points(self) -> tuple[DomainPointRef, ...]: ...

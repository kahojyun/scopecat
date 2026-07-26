"""One private axis model behind the opaque public scan handles."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import cast

from scopecat.authoring._parameter_contracts import (
    ParameterContract,
    ParameterValueContract,
    merge_parameter_contracts,
)
from scopecat.authoring._value_refs import (
    ScalarOperationOperand,
    ValueRef,
    internal_value_ref_parameter_contracts,
    internal_value_ref_parameter_lookup,
    internal_value_ref_point_id,
)
from scopecat.graph.relations.model import ParameterLookupUse
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_types import Scalar

type ScanValue = Quantity | EntityRef | str | int | float | bool | None
type ScanCenter = ValueRef | Quantity


class Scan:
    """Opaque public handle for one axis or a Cartesian bundle."""

    __slots__ = ()

    def __init__(self) -> None:
        msg = "Scan is an opaque handle; create scans with scopecat scan factories"
        raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class ValuesScanSource:
    values: tuple[ScanValue, ...]
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class AroundScanSource:
    """A linear axis; ``center=None`` inherits or reads the target parameter."""

    center: ScanCenter | None
    span: Quantity
    points: int


type ScanSource = ValuesScanSource | AroundScanSource


@dataclass(frozen=True, slots=True)
class ParameterCellOverlay:
    lookup: ValueRef


@dataclass(frozen=True, slots=True, repr=False)
class AxisSpec(Scan):
    target: ValueRef
    source: ScanSource
    overlay: ParameterCellOverlay | None = None

    @property
    def id(self) -> str:
        point_id = internal_value_ref_point_id(self.target)
        assert point_id is not None
        return point_id

    @property
    def value_type(self) -> Scalar:
        return cast("Scalar", self.target.value_type)


@dataclass(frozen=True, slots=True, repr=False)
class CartesianScan(Scan):
    axes: tuple[AxisSpec, ...]


def iter_scan_axes(scan: Scan) -> tuple[AxisSpec, ...]:
    """Return axes in deterministic declaration order."""

    if isinstance(scan, CartesianScan):
        return scan.axes
    if isinstance(scan, AxisSpec):
        return (scan,)
    raise TypeError("invalid scan handle")


def parameter_cell_lookup(
    axis: AxisSpec,
) -> tuple[
    ParameterLookupUse,
    tuple[tuple[str, ScalarOperationOperand], ...],
]:
    if axis.overlay is None:
        raise TypeError("scan axis does not overlay a parameter cell")
    lookup = internal_value_ref_parameter_lookup(axis.overlay.lookup)
    assert lookup is not None
    return lookup


def inherit_default_scan_fields(
    default: AxisSpec,
    replacement: AxisSpec,
) -> AxisSpec:
    """Preserve a default center when an override only supplies span/points."""

    if default.target.value_type != replacement.target.value_type:
        msg = (
            f"scan override for point {replacement.id!r} must reuse its "
            "declared value type"
        )
        raise TypeError(msg)
    if (
        isinstance(default.source, AroundScanSource)
        and isinstance(replacement.source, AroundScanSource)
        and replacement.source.center is None
    ):
        return replace(
            replacement,
            source=replace(
                replacement.source,
                center=default.source.center,
            ),
        )
    return replacement


def scan_parameter_contracts(scan: Scan) -> tuple[ParameterContract, ...]:
    return merge_parameter_contracts(
        *(
            merge_parameter_contracts(
                _value_parameter_contracts(
                    axis.overlay.lookup if axis.overlay is not None else None
                ),
                _source_parameter_contracts(axis),
            )
            for axis in iter_scan_axes(scan)
        )
    )


def _source_parameter_contracts(axis: AxisSpec) -> tuple[ParameterContract, ...]:
    source = axis.source
    if not isinstance(source, AroundScanSource):
        return ()
    if source.center is None:
        return (
            ParameterValueContract(
                parameter_id=axis.id,
                value_type=axis.value_type,
            ),
        )
    return _value_parameter_contracts(source.center)


def _value_parameter_contracts(value: object) -> tuple[ParameterContract, ...]:
    return (
        internal_value_ref_parameter_contracts(value)
        if isinstance(value, ValueRef)
        else ()
    )

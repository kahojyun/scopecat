"""Private typed intent graph behind the opaque public scan handles."""

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
from scopecat.compiler.relations.model import ParameterLookupUse
from scopecat.kernel.value_types import Scalar
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity

type ScanValue = Quantity | EntityRef | str | int | float | bool | None
type ScanCenter = ValueRef | Quantity


class Scan:
    """Opaque public handle for one scan or a Cartesian bundle."""

    __slots__ = ()

    def __init__(self) -> None:
        msg = "Scan is an opaque handle; create scans with scopecat scan factories"
        raise TypeError(msg)


@dataclass(frozen=True, slots=True, repr=False)
class ImplicitScanCenter:
    """Use the accepted parameter value unless a default scan supplies a center."""


@dataclass(frozen=True, slots=True, repr=False)
class ExplicitPointScanIntent(Scan):
    target: ValueRef
    values: tuple[ScanValue, ...]
    unit: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class CenteredPointScanIntent(Scan):
    target: ValueRef
    center: ScanCenter | ImplicitScanCenter
    span: Quantity
    points: int


@dataclass(frozen=True, slots=True, repr=False)
class ExplicitParameterScanIntent(Scan):
    target: ValueRef
    lookup: ValueRef
    values: tuple[ScanValue, ...]
    unit: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class CenteredParameterScanIntent(Scan):
    target: ValueRef
    lookup: ValueRef
    span: Quantity
    points: int


type PointScanIntent = ExplicitPointScanIntent | CenteredPointScanIntent
type ParameterScanIntent = ExplicitParameterScanIntent | CenteredParameterScanIntent
type ScanLeafIntent = PointScanIntent | ParameterScanIntent


@dataclass(frozen=True, slots=True, repr=False)
class CartesianScanIntent(Scan):
    scans: tuple[ScanLeafIntent, ...]


def iter_scan_leaves(scan: Scan) -> tuple[ScanLeafIntent, ...]:
    """Return scan leaves in deterministic declaration order."""

    if isinstance(scan, CartesianScanIntent):
        return scan.scans
    if isinstance(
        scan,
        ExplicitPointScanIntent
        | CenteredPointScanIntent
        | ExplicitParameterScanIntent
        | CenteredParameterScanIntent,
    ):
        return (scan,)
    msg = "invalid scan handle"
    raise TypeError(msg)


def scan_point_id(scan: ScanLeafIntent) -> str:
    point_id = internal_value_ref_point_id(scan.target)
    assert point_id is not None  # noqa: S101
    return point_id


def parameter_scan_lookup(
    scan: ParameterScanIntent,
) -> tuple[
    ParameterLookupUse,
    tuple[tuple[str, ScalarOperationOperand], ...],
]:
    lookup = internal_value_ref_parameter_lookup(scan.lookup)
    assert lookup is not None  # noqa: S101
    return lookup


def inherit_default_scan_fields(
    default: ScanLeafIntent,
    replacement: ScanLeafIntent,
) -> ScanLeafIntent:
    """Preserve a centered default for an implicit-center override."""

    if default.target.value_type != replacement.target.value_type:
        msg = (
            f"scan override for point {scan_point_id(replacement)!r} must reuse its "
            "declared value type"
        )
        raise TypeError(msg)
    match default, replacement:
        case (
            CenteredPointScanIntent(),
            CenteredPointScanIntent(center=ImplicitScanCenter()),
        ):
            return replace(
                replacement,
                center=default.center,
            )
        case _:
            return replacement


def scan_parameter_contracts(scan: Scan) -> tuple[ParameterContract, ...]:
    match scan:
        case ExplicitPointScanIntent():
            return ()
        case CenteredPointScanIntent(center=ImplicitScanCenter()):
            return (
                ParameterValueContract(
                    parameter_id=scan_point_id(scan),
                    value_type=cast("Scalar", scan.target.value_type),
                ),
            )
        case CenteredPointScanIntent():
            return _value_parameter_contracts(scan.center)
        case ExplicitParameterScanIntent():
            return merge_parameter_contracts(
                internal_value_ref_parameter_contracts(scan.lookup),
                *(_value_parameter_contracts(value) for value in scan.values),
            )
        case CenteredParameterScanIntent():
            return internal_value_ref_parameter_contracts(scan.lookup)
        case CartesianScanIntent():
            return merge_parameter_contracts(
                *(scan_parameter_contracts(child) for child in scan.scans)
            )
        case _:
            msg = "invalid scan handle"
            raise TypeError(msg)


def _value_parameter_contracts(value: object) -> tuple[ParameterContract, ...]:
    return (
        internal_value_ref_parameter_contracts(value)
        if isinstance(value, ValueRef)
        else ()
    )

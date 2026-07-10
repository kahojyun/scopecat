"""Private typed intent graph behind the opaque public scan handles."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from scopecat.authoring._parameter_contracts import (
    ParameterContract,
    merge_parameter_contracts,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_value_ref_parameter_contracts,
)
from scopecat.authoring.values import ParameterKeyInput
from scopecat.models.entity import EntityRef
from scopecat.models.parameter import Quantity

type ScanValue = Quantity | EntityRef | str | int | float | bool | None
type ScanCenter = ValueRef | Quantity


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Scan:
    """Opaque public handle for one scan or an explicit scan group."""

    def __init__(self) -> None:
        msg = "Scan is an opaque handle; create scans with scopecat scan factories"
        raise TypeError(msg)


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ParameterRow:
    """Opaque selection of one row in a parameter table."""

    def __init__(self) -> None:
        msg = "ParameterRow is an opaque handle; create rows with scopecat.param_row"
        raise TypeError(msg)


@dataclass(frozen=True, slots=True, repr=False)
class ParameterRowIntent(ParameterRow):
    table_id: str
    key: tuple[tuple[str, ParameterKeyInput], ...]


@dataclass(frozen=True, slots=True, repr=False)
class PointScanIntent(Scan):
    target: ValueRef
    point_id: str
    point_values: tuple[ScanValue, ...] = ()
    unit: str | None = None
    center: ScanCenter | None = None
    span: Quantity | str | None = None
    point_count: int | None = None
    implicit_center: bool = False
    parameter_contracts: tuple[ParameterContract, ...] = ()


@dataclass(frozen=True, slots=True, repr=False)
class ParameterScanIntent(Scan):
    target: ValueRef
    point_id: str
    table_id: str
    key: tuple[tuple[str, ParameterKeyInput], ...]
    column: str
    values: tuple[ScanValue, ...]
    unit: str | None = None
    parameter_contracts: tuple[ParameterContract, ...] = ()


@dataclass(frozen=True, slots=True, repr=False)
class ScanGroupIntent(Scan):
    kind: Literal["cartesian", "zip"]
    scans: tuple[Scan, ...]


type ScanLeafIntent = PointScanIntent | ParameterScanIntent


def iter_scan_leaves(scan: Scan) -> tuple[ScanLeafIntent, ...]:
    """Return scan leaves in deterministic declaration order."""

    if isinstance(scan, ScanGroupIntent):
        return tuple(leaf for child in scan.scans for leaf in iter_scan_leaves(child))
    if isinstance(scan, PointScanIntent | ParameterScanIntent):
        return (scan,)
    msg = "invalid scan handle"
    raise TypeError(msg)


def scan_point_id(scan: ScanLeafIntent) -> str:
    return scan.point_id


def replace_scan_group(scan: ScanGroupIntent, scans: Sequence[Scan]) -> Scan:
    return ScanGroupIntent(kind=scan.kind, scans=tuple(scans))


def inherit_default_scan_fields(
    default: ScanLeafIntent,
    replacement: ScanLeafIntent,
) -> Scan:
    """Preserve a centered default for an implicit-center override."""

    if default.target.value_type != replacement.target.value_type:
        msg = (
            f"scan override for point {replacement.point_id!r} must reuse its "
            "declared value type"
        )
        raise TypeError(msg)
    if not isinstance(default, PointScanIntent) or not isinstance(
        replacement, PointScanIntent
    ):
        return replacement
    if replacement.point_values or not replacement.implicit_center:
        return replacement
    if default.center is None and not default.implicit_center:
        return replacement
    return PointScanIntent(
        target=replacement.target,
        point_id=replacement.point_id,
        span=replacement.span,
        point_count=replacement.point_count,
        center=default.center,
        implicit_center=default.implicit_center,
        parameter_contracts=default.parameter_contracts,
    )


def scan_parameter_contracts(scan: Scan) -> tuple[ParameterContract, ...]:
    if isinstance(scan, PointScanIntent):
        return scan.parameter_contracts
    if isinstance(scan, ParameterScanIntent):
        return merge_parameter_contracts(
            *(
                _value_parameter_contracts(value)
                for value in (*dict(scan.key).values(), *scan.values)
            ),
            scan.parameter_contracts,
        )
    if isinstance(scan, ScanGroupIntent):
        return merge_parameter_contracts(
            *(scan_parameter_contracts(child) for child in scan.scans)
        )
    msg = "invalid scan handle"
    raise TypeError(msg)


def _value_parameter_contracts(value: object) -> tuple[ParameterContract, ...]:
    return (
        internal_value_ref_parameter_contracts(value)
        if isinstance(value, ValueRef)
        else ()
    )


__all__ = [
    "ParameterRow",
    "ParameterRowIntent",
    "ParameterScanIntent",
    "PointScanIntent",
    "Scan",
    "ScanCenter",
    "ScanGroupIntent",
    "ScanLeafIntent",
    "ScanValue",
    "inherit_default_scan_fields",
    "iter_scan_leaves",
    "replace_scan_group",
    "scan_parameter_contracts",
    "scan_point_id",
]

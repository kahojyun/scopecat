"""Resolved domain extensions proposed while an admitted run is active."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import product
from types import MappingProxyType
from typing import Literal, cast

from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.points import PointProposalSource
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_data import CellValue

type AdaptiveScope = Literal["per_region", "global"]
type DomainFragmentLayout = Literal["grid", "point_cloud"]


@dataclass(frozen=True, slots=True)
class ResolvedDomainAxis:
    """One concrete coordinate column in a runtime domain fragment."""

    id: str
    values: tuple[CellValue, ...]

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("domain fragment axis id must be non-empty")
        if not self.values:
            raise ValueError("domain fragment axis values must be non-empty")

    @classmethod
    def values_axis(
        cls,
        id: str,
        values: Sequence[CellValue],
    ) -> ResolvedDomainAxis:
        return cls(id=id, values=tuple(values))

    @classmethod
    def range_axis(
        cls,
        id: str,
        start: float | Quantity,
        stop: float | Quantity,
        *,
        points: int,
    ) -> ResolvedDomainAxis:
        return cls(id=id, values=_linear_values(start, stop, points=points))

    @classmethod
    def around_axis(
        cls,
        id: str,
        center: float | Quantity,
        span: float | Quantity,
        *,
        points: int,
    ) -> ResolvedDomainAxis:
        if isinstance(center, Quantity):
            if not isinstance(span, Quantity):
                raise TypeError("quantity centers require a quantity span")
            converted_span = span.to(center.unit)
            half = converted_span / 2
            return cls.range_axis(
                id,
                center - half,
                center + half,
                points=points,
            )
        if isinstance(span, Quantity):
            raise TypeError("numeric centers require a numeric span")
        return cls.range_axis(
            id,
            center - span / 2,
            center + span / 2,
            points=points,
        )


@dataclass(frozen=True, slots=True)
class ResolvedDomainFragment:
    """A compact, fully concrete scan domain over admitted adaptive axes."""

    axes: tuple[ResolvedDomainAxis, ...]
    layout: DomainFragmentLayout = "grid"

    def __post_init__(self) -> None:
        ids = tuple(axis.id for axis in self.axes)
        if not ids:
            raise ValueError("domain fragment requires at least one coordinate axis")
        if len(ids) != len(set(ids)):
            raise ValueError("domain fragment axis ids must be unique")
        if self.layout == "point_cloud":
            lengths = {len(axis.values) for axis in self.axes}
            if len(lengths) > 1:
                raise ValueError("point-cloud fragment columns must have equal lengths")

    @classmethod
    def grid(cls, *axes: ResolvedDomainAxis) -> ResolvedDomainFragment:
        return cls(axes=tuple(axes), layout="grid")

    @classmethod
    def points(
        cls,
        rows: Sequence[Mapping[str, CellValue]],
    ) -> ResolvedDomainFragment:
        selected = tuple(rows)
        if not selected:
            raise ValueError("point-cloud fragment requires at least one row")
        coordinate_ids = tuple(selected[0])
        expected = set(coordinate_ids)
        if not expected or any(set(row) != expected for row in selected):
            raise ValueError(
                "point-cloud fragment rows must contain the same coordinates"
            )
        return cls(
            axes=tuple(
                ResolvedDomainAxis(
                    coordinate_id,
                    tuple(row[coordinate_id] for row in selected),
                )
                for coordinate_id in coordinate_ids
            ),
            layout="point_cloud",
        )

    @property
    def coordinate_ids(self) -> tuple[str, ...]:
        return tuple(axis.id for axis in self.axes)

    @property
    def point_count(self) -> int:
        if self.layout == "point_cloud":
            return len(self.axes[0].values)
        count = 1
        for axis in self.axes:
            count *= len(axis.values)
        return count

    def rows(self) -> Iterator[dict[str, CellValue]]:
        """Expand logical rows lazily in declaration order."""

        if self.layout == "point_cloud":
            return (
                {axis.id: axis.values[index] for axis in self.axes}
                for index in range(self.point_count)
            )
        return (
            dict(zip(self.coordinate_ids, values, strict=True))
            for values in product(*(axis.values for axis in self.axes))
        )

    @property
    def fingerprint(self) -> str:
        return "sha256:" + stable_content_hash(
            content_fingerprint(
                {
                    "schema": "scopecat.resolved_domain_fragment.v1",
                    "layout": self.layout,
                    "axes": tuple(
                        {"id": axis.id, "values": axis.values} for axis in self.axes
                    ),
                }
            )
        )


@dataclass(frozen=True, slots=True)
class AdaptiveRegion:
    """Stable outer-domain partition visible to optimizers and operators."""

    id: str
    coordinates: Mapping[str, CellValue]
    point_count: int
    completed_point_count: int
    revision: int
    point_limit: int
    closed: bool = False

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("adaptive region id must be non-empty")
        if (
            min(
                self.point_count,
                self.completed_point_count,
                self.revision,
                self.point_limit,
            )
            < 0
        ):
            raise ValueError("adaptive region counters must be non-negative")
        if self.completed_point_count > self.point_count:
            raise ValueError("completed region points cannot exceed accepted points")
        if self.point_count > self.point_limit:
            raise ValueError("accepted region points cannot exceed its limit")
        object.__setattr__(
            self, "coordinates", MappingProxyType(dict(self.coordinates))
        )

    @property
    def remaining_point_count(self) -> int:
        return self.point_limit - self.point_count


@dataclass(frozen=True, slots=True)
class DomainProposalAttempt:
    """One compatible domain extension with region-scoped freshness."""

    fragment: ResolvedDomainFragment
    region_ids: tuple[str, ...] = ()
    source: PointProposalSource = "optimizer"
    based_on_region_revisions: Mapping[str, int] = MappingProxyType({})

    def __post_init__(self) -> None:
        if len(self.region_ids) != len(set(self.region_ids)):
            raise ValueError("domain proposal region ids must be unique")
        if any(not region_id for region_id in self.region_ids):
            raise ValueError("domain proposal region ids must be non-empty")
        if any(revision < 0 for revision in self.based_on_region_revisions.values()):
            raise ValueError("domain proposal revisions must be non-negative")
        object.__setattr__(
            self,
            "based_on_region_revisions",
            MappingProxyType(dict(self.based_on_region_revisions)),
        )

    @property
    def proposal_fingerprint(self) -> str:
        return "sha256:" + stable_content_hash(
            content_fingerprint(
                {
                    "schema": "scopecat.domain_proposal_attempt.v1",
                    "fragment": self.fragment,
                    "region_ids": self.region_ids,
                    "source": self.source,
                    "based_on_region_revisions": dict(self.based_on_region_revisions),
                }
            )
        )


@dataclass(frozen=True, slots=True)
class RegionOptimizationComplete:
    """Stop adaptive proposals for one outer-domain region only."""

    reason: str = "region optimizer completed"

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("region completion reason must be non-empty")


def _linear_values(
    start: float | Quantity,
    stop: float | Quantity,
    *,
    points: int,
) -> tuple[CellValue, ...]:
    if points < 2:
        raise ValueError("range fragments require at least two points")
    if isinstance(start, Quantity):
        if not isinstance(stop, Quantity):
            raise TypeError("range endpoints must both be quantities")
        converted = stop.to(start.unit)
        return tuple(
            Quantity(
                start.value + (converted.value - start.value) * index / (points - 1),
                start.unit,
            )
            for index in range(points)
        )
    if isinstance(stop, Quantity):
        raise TypeError("range endpoints must both be numeric")
    if isinstance(start, bool) or isinstance(stop, bool):
        raise TypeError("boolean coordinates do not support linear ranges")
    values = tuple(
        start + (stop - start) * index / (points - 1) for index in range(points)
    )
    if (
        isinstance(start, int)
        and isinstance(stop, int)
        and all(value.is_integer() for value in values)
    ):
        return cast("tuple[CellValue, ...]", tuple(int(value) for value in values))
    return cast("tuple[CellValue, ...]", values)


__all__ = [
    "AdaptiveRegion",
    "AdaptiveScope",
    "DomainFragmentLayout",
    "DomainProposalAttempt",
    "RegionOptimizationComplete",
    "ResolvedDomainAxis",
    "ResolvedDomainFragment",
]

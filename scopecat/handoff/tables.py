"""Table and declared plot projections for handoff packages."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass


def _freeze_records(
    rows: list[dict[str, str]],
    columns: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    if not columns:
        raise ValueError("handoff table requires at least one column")
    if any(not isinstance(column, str) or column == "" for column in columns):
        raise ValueError("handoff table requires non-empty string columns")
    if len(set(columns)) != len(columns):
        raise ValueError("handoff table requires unique columns")

    expected = set(columns)
    frozen_rows = []
    for row in rows:
        if set(row) != expected:
            raise ValueError("handoff table rows must match columns")
        if any(not isinstance(row[column], str) for column in columns):
            raise ValueError("handoff table row values must be strings")
        frozen_rows.append(tuple(row[column] for column in columns))
    return tuple(frozen_rows)


@dataclass(frozen=True)
class HandoffTable:
    """String-valued table projection without dataframe semantics."""

    columns: tuple[str, ...]
    _rows: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        _freeze_records(self.rows, self.columns)

    @classmethod
    def from_records(cls, columns: list[str], rows: list[dict[str, str]]) -> HandoffTable:
        frozen_columns = tuple(columns)
        return cls(columns=frozen_columns, _rows=_freeze_records(rows, frozen_columns))

    @property
    def row_count(self) -> int:
        return len(self._rows)

    @property
    def rows(self) -> tuple[dict[str, str], ...]:
        return tuple(dict(zip(self.columns, row, strict=True)) for row in self._rows)

    def row(self, index: int) -> dict[str, str]:
        return dict(zip(self.columns, self._rows[index], strict=True))

    def column(self, name: str) -> tuple[str, ...]:
        try:
            index = self.columns.index(name)
        except ValueError as exc:
            raise KeyError(name) from exc
        return tuple(row[index] for row in self._rows)

    def to_records(self) -> list[dict[str, str]]:
        return list(self.rows)

    def __iter__(self) -> Iterator[dict[str, str]]:
        return iter(self.rows)

    def __len__(self) -> int:
        return self.row_count


@dataclass(frozen=True)
class HandoffPlotSeries:
    """Declared plot series as string-valued points."""

    source: str
    x_name: str
    y_name: str
    _points: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source:
            raise ValueError("handoff plot series requires a source")
        if not isinstance(self.x_name, str) or not self.x_name:
            raise ValueError("handoff plot series requires an x column")
        if not isinstance(self.y_name, str) or not self.y_name:
            raise ValueError("handoff plot series requires a y column")
        for point in self._points:
            if len(point) != 2:
                raise ValueError("handoff plot series points must have x and y")
            if not isinstance(point[0], str) or not isinstance(point[1], str):
                raise ValueError("handoff plot series point values must be strings")

    @classmethod
    def from_points(
        cls,
        *,
        source: str,
        x_name: str,
        y_name: str,
        points: list[dict[str, str]],
    ) -> HandoffPlotSeries:
        frozen_points = []
        for point in points:
            if set(point) != {"x", "y"}:
                raise ValueError("handoff plot series points must have x and y")
            if not isinstance(point["x"], str) or not isinstance(point["y"], str):
                raise ValueError("handoff plot series point values must be strings")
            frozen_points.append((point["x"], point["y"]))
        return cls(
            source=source,
            x_name=x_name,
            y_name=y_name,
            _points=tuple(frozen_points),
        )

    @property
    def points(self) -> tuple[dict[str, str], ...]:
        return tuple({"x": x, "y": y} for x, y in self._points)

    @property
    def x(self) -> tuple[str, ...]:
        return tuple(point[0] for point in self._points)

    @property
    def y(self) -> tuple[str, ...]:
        return tuple(point[1] for point in self._points)

    def to_records(self) -> list[dict[str, str]]:
        return list(self.points)

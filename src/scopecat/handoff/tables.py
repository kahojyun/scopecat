"""Table projections for handoff packages."""

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

"""Direct whole-table sources passed to a domain compiler."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from scopecat.kernel.value_data import CellValue, Row


@dataclass(frozen=True, slots=True)
class LiteralTableSource:
    rows: tuple[Row, ...]


@dataclass(frozen=True, slots=True)
class ParameterTableSource:
    parameter_id: str


@dataclass(frozen=True, slots=True)
class InputTableSource:
    input_id: str


type TableSource = LiteralTableSource | ParameterTableSource | InputTableSource


def literal_table_source(
    rows: Sequence[Mapping[str, CellValue]],
) -> LiteralTableSource:
    """Snapshot rows at the trusted authoring boundary."""

    return LiteralTableSource(tuple(dict(row) for row in rows))

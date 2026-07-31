"""Point-local overlays for statically selected parameter cells."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from scopecat.compiler.relations.context import ParameterRelationData
from scopecat.compiler.relations.specialization import ParameterCellBinding
from scopecat.kernel.value_data import CellValue
from scopecat.program.expressions import point_col


@dataclass(frozen=True, slots=True)
class PointParameterOverlay:
    """Bind one accepted parameter cell to one scan coordinate."""

    table_id: str
    row_index: int
    key: dict[str, CellValue]
    column_id: str
    axis_id: str


def resolve_point_parameters(
    base: ParameterRelationData,
    overlays: Sequence[PointParameterOverlay],
    *,
    point_row: Mapping[str, CellValue],
) -> ParameterRelationData:
    """Apply every statically bound cell overlay for one logical point."""

    resolved = base
    for overlay in overlays:
        resolved = resolved.with_table_cell(
            overlay.table_id,
            row_index=overlay.row_index,
            column_id=overlay.column_id,
            value=point_row[overlay.axis_id],
        )
    return resolved


def parameter_cell_bindings(
    overlays: Sequence[PointParameterOverlay],
) -> tuple[ParameterCellBinding, ...]:
    """Project bound overlays into scalar-specialization bindings."""

    return tuple(
        ParameterCellBinding(
            table_id=overlay.table_id,
            key=tuple(sorted(overlay.key.items())),
            column_id=overlay.column_id,
            replacement=point_col(overlay.axis_id),
        )
        for overlay in overlays
    )

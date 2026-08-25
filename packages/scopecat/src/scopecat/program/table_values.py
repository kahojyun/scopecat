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


@dataclass(frozen=True, slots=True)
class TopologyEntitySetSource:
    """A config-bound entity-set selection retained in the logical program."""

    entity_kind: str
    count: int | None = None
    connected: bool = False
    anchor_id: str | None = None
    connection_kind: str | None = None

    def __post_init__(self) -> None:
        if not self.entity_kind:
            raise ValueError("topology entity selections require an entity kind")
        if self.count is not None and self.count <= 0:
            raise ValueError("topology entity selection count must be positive")
        if self.anchor_id is not None and not self.anchor_id:
            raise ValueError("topology entity selection anchor must be non-empty")
        if self.connection_kind is not None and not self.connection_kind:
            raise ValueError(
                "topology entity selection connection kind must be non-empty"
            )
        if not self.connected and (
            self.anchor_id is not None or self.connection_kind is not None
        ):
            raise ValueError(
                "topology entity selection anchors and connection kinds require "
                "connected=True"
            )


@dataclass(frozen=True, slots=True)
class TopologyConnectionSetSource:
    """A config-bound selection of typed topology edges and their entities."""

    endpoint_entity_kind: str
    connection_entity_kind: str
    connection_kind: str | None = None
    matching: int | None = None

    def __post_init__(self) -> None:
        if not self.endpoint_entity_kind:
            raise ValueError("topology connection selections require an endpoint kind")
        if not self.connection_entity_kind:
            raise ValueError("topology connection selections require an entity kind")
        if self.connection_kind is not None and not self.connection_kind:
            raise ValueError("topology connection selection kind must be non-empty")
        if self.matching is not None and self.matching < 0:
            raise ValueError("topology connection matching must be non-negative")


type TableSource = (
    LiteralTableSource
    | ParameterTableSource
    | InputTableSource
    | TopologyEntitySetSource
    | TopologyConnectionSetSource
)


def literal_table_source(
    rows: Sequence[Mapping[str, CellValue]],
) -> LiteralTableSource:
    """Snapshot rows at the trusted authoring boundary."""

    return LiteralTableSource(tuple(dict(row) for row in rows))

"""Typed, target-neutral views of compiled physical realizations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from scopecat.kernel.json_types import JsonValue


@dataclass(frozen=True, slots=True)
class CompiledInspectionFact:
    """One named target fact suitable for display and transport."""

    id: str
    value: JsonValue
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class CompiledProgramInspectionNode:
    """One bounded, identity-bearing node in a compiler inspection layer."""

    id: str
    kind: str
    label: str
    parent_id: str | None = None
    child_count: int = 0
    entity_ids: tuple[str, ...] = ()
    entity_count: int = 0
    entity_ids_truncated: bool = False
    resource_ids: tuple[str, ...] = ()
    resource_count: int = 0
    resource_ids_truncated: bool = False
    result_ids: tuple[str, ...] = ()
    result_count: int = 0
    result_ids_truncated: bool = False
    start_seconds: str | None = None
    duration_seconds: str | None = None
    facts: tuple[CompiledInspectionFact, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.entity_count == 0 and self.entity_ids:
            object.__setattr__(self, "entity_count", len(self.entity_ids))
        if self.resource_count == 0 and self.resource_ids:
            object.__setattr__(self, "resource_count", len(self.resource_ids))
        if self.result_count == 0 and self.result_ids:
            object.__setattr__(self, "result_count", len(self.result_ids))


@dataclass(frozen=True, slots=True)
class CompiledProgramInspectionQuery:
    """One bounded server-side node query for a program layer."""

    layer_id: str
    offset: int = 0
    limit: int = 128
    parent_id: str | None = None
    entity_id: str | None = None
    resource_id: str | None = None
    kind: str | None = None
    text: str | None = None

    def __post_init__(self) -> None:
        if not self.layer_id:
            raise ValueError("inspection queries require a layer id")
        if self.offset < 0:
            raise ValueError("inspection query offsets must be non-negative")
        if not 1 <= self.limit <= 512:
            raise ValueError("inspection query limits must be between 1 and 512")


@dataclass(frozen=True, slots=True)
class CompiledProgramInspectionPage:
    """Page metadata for one layer after server-side filtering."""

    offset: int
    limit: int
    matching_node_count: int
    returned_node_count: int
    next_offset: int | None = None


@dataclass(frozen=True, slots=True)
class CompiledProgramInspectionLayer:
    """A bounded semantic projection of one program compilation stage."""

    id: str
    label: str
    kind: str
    node_count: int
    nodes_truncated: bool
    root_ids: tuple[str, ...]
    nodes: tuple[CompiledProgramInspectionNode, ...]
    page: CompiledProgramInspectionPage
    facts: tuple[CompiledInspectionFact, ...] = ()


@dataclass(frozen=True, slots=True)
class CompiledProgramInspectionLink:
    """A stable many-to-many lowering relation between inspection nodes."""

    source_layer_id: str
    source_node_id: str
    target_layer_id: str
    target_node_id: str
    relation: str


@dataclass(frozen=True, slots=True)
class CompiledProgramInspection:
    """Structured multi-layer view of one bounded compiled program variant."""

    dialect_id: str
    program_id: str
    layers: tuple[CompiledProgramInspectionLayer, ...]
    links: tuple[CompiledProgramInspectionLink, ...] = ()
    query: CompiledProgramInspectionQuery | None = None
    warnings: tuple[str, ...] = ()
    schema_id: Literal["scopecat.compiled_program_inspection.v2"] = (
        "scopecat.compiled_program_inspection.v2"
    )


def query_compiled_program_nodes(
    layer_id: str,
    nodes: tuple[CompiledProgramInspectionNode, ...],
    *,
    query: CompiledProgramInspectionQuery | None,
    default_limit: int,
) -> tuple[tuple[CompiledProgramInspectionNode, ...], CompiledProgramInspectionPage]:
    """Filter and page nodes without exposing an unbounded transport payload."""

    if query is not None and query.layer_id != layer_id:
        return (), CompiledProgramInspectionPage(
            offset=0,
            limit=default_limit,
            matching_node_count=len(nodes),
            returned_node_count=0,
            next_offset=0 if nodes else None,
        )
    selected_query = query if query is not None and query.layer_id == layer_id else None
    matches = tuple(
        node
        for node in nodes
        if selected_query is None or _matches_program_node(node, selected_query)
    )
    offset = 0 if selected_query is None else selected_query.offset
    limit = (
        default_limit
        if selected_query is None
        else min(selected_query.limit, default_limit)
    )
    selected = tuple(
        _bound_program_node_references(node, query=selected_query)
        for node in matches[offset : offset + limit]
    )
    next_offset = offset + len(selected)
    if next_offset >= len(matches):
        next_offset = None
    return selected, CompiledProgramInspectionPage(
        offset=offset,
        limit=limit,
        matching_node_count=len(matches),
        returned_node_count=len(selected),
        next_offset=next_offset,
    )


def _matches_program_node(
    node: CompiledProgramInspectionNode,
    query: CompiledProgramInspectionQuery,
) -> bool:
    if query.parent_id is not None and node.parent_id != query.parent_id:
        return False
    if query.entity_id is not None and query.entity_id not in node.entity_ids:
        return False
    if query.resource_id is not None and query.resource_id not in node.resource_ids:
        return False
    if query.kind is not None and node.kind != query.kind:
        return False
    if query.text is None:
        return True
    needle = query.text.casefold()
    values = (
        node.id,
        node.kind,
        node.label,
        *node.entity_ids,
        *node.resource_ids,
        *node.result_ids,
        *node.warnings,
    )
    return any(needle in value.casefold() for value in values)


def _bound_program_node_references(
    node: CompiledProgramInspectionNode,
    *,
    query: CompiledProgramInspectionQuery | None,
    limit: int = 64,
) -> CompiledProgramInspectionNode:
    return replace(
        node,
        entity_ids=_bounded_references(
            node.entity_ids, query.entity_id if query else None, limit
        ),
        entity_count=len(node.entity_ids),
        entity_ids_truncated=len(node.entity_ids) > limit,
        resource_ids=_bounded_references(
            node.resource_ids,
            query.resource_id if query else None,
            limit,
        ),
        resource_count=len(node.resource_ids),
        resource_ids_truncated=len(node.resource_ids) > limit,
        result_ids=node.result_ids[:limit],
        result_count=len(node.result_ids),
        result_ids_truncated=len(node.result_ids) > limit,
    )


def _bounded_references(
    values: tuple[str, ...],
    preferred: str | None,
    limit: int,
) -> tuple[str, ...]:
    if preferred is None or preferred not in values[:limit]:
        return (
            values[:limit]
            if preferred is None or preferred not in values
            else (
                preferred,
                *tuple(value for value in values if value != preferred)[: limit - 1],
            )
        )
    return values[:limit]


@dataclass(frozen=True, slots=True)
class CompiledWaveformInspection:
    """Bounded samples and stable identity for one physical waveform."""

    channel_id: str
    instrument_id: str
    peak_abs: float
    rms: float
    source_sample_count: int
    samples_sha256: str
    sample_indices: tuple[int, ...]
    samples: tuple[float, ...]
    downsampling: Literal["none", "minmax"]


@dataclass(frozen=True, slots=True)
class CompiledPointInspection:
    """One batch-independent physical realization of a point candidate."""

    realization_fingerprint: str
    target_entry_id: str
    facts: tuple[CompiledInspectionFact, ...]
    waveform_count: int
    waveforms_truncated: bool
    waveforms: tuple[CompiledWaveformInspection, ...]
    warnings: tuple[str, ...] = ()

    def fact(self, fact_id: str) -> CompiledInspectionFact:
        return next(fact for fact in self.facts if fact.id == fact_id)


@dataclass(frozen=True, slots=True)
class CompiledInspectionBounds:
    """Hard response budgets applied to one transient inspection."""

    max_points: int
    max_waveforms_per_point: int
    max_samples_per_waveform: int


@dataclass(frozen=True, slots=True)
class CompiledArtifactInspection:
    """Common inspection envelope shared by pre-run and running views."""

    kind: str
    facts: tuple[CompiledInspectionFact, ...]
    point_count: int
    points_truncated: bool
    bounds: CompiledInspectionBounds
    points: tuple[CompiledPointInspection, ...]
    program: CompiledProgramInspection | None = None
    warnings: tuple[str, ...] = ()
    schema_id: Literal["scopecat.compiled_artifact_inspection.v2"] = (
        "scopecat.compiled_artifact_inspection.v2"
    )

    def fact(self, fact_id: str) -> CompiledInspectionFact:
        return next(fact for fact in self.facts if fact.id == fact_id)


__all__ = [
    "CompiledArtifactInspection",
    "CompiledInspectionBounds",
    "CompiledInspectionFact",
    "CompiledPointInspection",
    "CompiledProgramInspection",
    "CompiledProgramInspectionLayer",
    "CompiledProgramInspectionLink",
    "CompiledProgramInspectionNode",
    "CompiledProgramInspectionPage",
    "CompiledProgramInspectionQuery",
    "CompiledWaveformInspection",
    "query_compiled_program_nodes",
]

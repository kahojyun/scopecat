from __future__ import annotations

import pytest

from scopecat.inspection import (
    CompiledProgramInspectionNode,
    CompiledProgramInspectionNodeIndex,
    CompiledProgramInspectionQuery,
    query_compiled_program_node_index,
    query_compiled_program_nodes,
)


def test_program_node_queries_bound_large_reference_sets() -> None:
    node = CompiledProgramInspectionNode(
        id="logical:map",
        kind="parallel_each",
        label="parallel_each $targets (100 entities)",
        entity_ids=tuple(f"q{index}" for index in range(100)),
    )

    selected, page = query_compiled_program_nodes(
        "logical",
        (node,),
        query=CompiledProgramInspectionQuery(
            layer_id="logical",
            entity_id="q99",
        ),
        default_limit=128,
    )

    assert page.matching_node_count == 1
    [bounded] = selected
    assert bounded.entity_count == 100
    assert bounded.entity_ids_truncated
    assert len(bounded.entity_ids) == 64
    assert bounded.entity_ids[0] == "q99"


def test_program_node_cursor_is_bound_to_snapshot_and_filters() -> None:
    nodes = tuple(
        CompiledProgramInspectionNode(
            id=f"scheduled:{index}",
            kind="play",
            label=f"pulse {index}",
        )
        for index in range(5)
    )
    query = CompiledProgramInspectionQuery(
        layer_id="scheduled",
        snapshot_id="artifact-a",
        limit=2,
        kind="play",
    )

    first, first_page = query_compiled_program_nodes(
        "scheduled",
        nodes,
        query=query,
        default_limit=2,
        snapshot_id="artifact-a",
    )
    assert [node.id for node in first] == ["scheduled:0", "scheduled:1"]
    assert first_page.next_cursor is not None

    second, second_page = query_compiled_program_nodes(
        "scheduled",
        nodes,
        query=CompiledProgramInspectionQuery(
            layer_id="scheduled",
            snapshot_id="artifact-a",
            cursor=first_page.next_cursor,
            limit=2,
            kind="play",
        ),
        default_limit=2,
        snapshot_id="artifact-a",
    )
    assert [node.id for node in second] == ["scheduled:2", "scheduled:3"]
    assert second_page.previous_cursor is not None

    with pytest.raises(ValueError, match="cursor does not match"):
        query_compiled_program_nodes(
            "scheduled",
            nodes,
            query=CompiledProgramInspectionQuery(
                layer_id="scheduled",
                snapshot_id="artifact-a",
                cursor=first_page.next_cursor,
                limit=2,
                kind="acquire",
            ),
            default_limit=2,
            snapshot_id="artifact-a",
        )
    with pytest.raises(ValueError, match="snapshot does not match"):
        query_compiled_program_nodes(
            "scheduled",
            nodes,
            query=CompiledProgramInspectionQuery(
                layer_id="scheduled",
                snapshot_id="artifact-b",
                limit=2,
            ),
            default_limit=2,
            snapshot_id="artifact-a",
        )


def test_unfiltered_program_pages_only_materialize_returned_nodes() -> None:
    loaded: list[int] = []

    def node_at(
        ordinal: int,
        _query: CompiledProgramInspectionQuery | None,
    ) -> CompiledProgramInspectionNode:
        loaded.append(ordinal)
        return CompiledProgramInspectionNode(
            id=f"scheduled:{ordinal}",
            kind="play",
            label=f"pulse {ordinal}",
        )

    index = CompiledProgramInspectionNodeIndex(
        node_count=100_000,
        node_at=node_at,
    )
    first = query_compiled_program_node_index(
        "scheduled",
        index,
        query=CompiledProgramInspectionQuery(
            layer_id="scheduled",
            snapshot_id="artifact-a",
            limit=2,
        ),
        default_limit=2,
        snapshot_id="artifact-a",
    )

    assert [node.id for node in first.nodes] == ["scheduled:0", "scheduled:1"]
    assert loaded == [0, 1]
    assert first.page.matching_node_count == 100_000
    assert first.page.next_cursor is not None

    second = query_compiled_program_node_index(
        "scheduled",
        index,
        query=CompiledProgramInspectionQuery(
            layer_id="scheduled",
            snapshot_id="artifact-a",
            cursor=first.page.next_cursor,
            limit=2,
        ),
        default_limit=2,
        snapshot_id="artifact-a",
    )

    assert [node.id for node in second.nodes] == ["scheduled:2", "scheduled:3"]
    assert loaded == [0, 1, 2, 3]

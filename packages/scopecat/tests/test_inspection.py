from __future__ import annotations

from scopecat.inspection import (
    CompiledProgramInspectionNode,
    CompiledProgramInspectionQuery,
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

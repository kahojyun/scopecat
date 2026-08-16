"""Measure exact and inverted-index program inspection projection."""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from dataclasses import asdict
from typing import cast

from benchmarks.record import BENCHMARK_RESULT_PREFIX, benchmark_record_header
from scopecat.inspection import (
    CompiledProgramInspectionInvertedIndexBuilder,
    CompiledProgramInspectionLayerIndex,
    CompiledProgramInspectionNode,
    CompiledProgramInspectionNodeIndex,
    CompiledProgramInspectionQuery,
)


def _options() -> tuple[int, int]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=int, default=10_000)
    parser.add_argument("--page-size", type=int, default=128)
    options = parser.parse_args()
    node_count = cast("int", options.nodes)
    page_size = cast("int", options.page_size)
    if node_count <= 0:
        raise ValueError("node count must be positive")
    if not 1 <= page_size <= 512:
        raise ValueError("page size must be between one and 512")
    return node_count, page_size


def _benchmark(node_count: int, page_size: int) -> dict[str, object]:
    tracemalloc.start()
    index_started = time.perf_counter()
    exact_ordinals = {
        f"physical:event:{ordinal}": ordinal for ordinal in range(node_count)
    }
    inverted = CompiledProgramInspectionInvertedIndexBuilder()
    for ordinal in range(node_count):
        inverted.add(
            ordinal,
            parent_id=None,
            kind="placement",
            entity_ids=(f"q{ordinal}",),
            resource_ids=(f"channel-{ordinal % 64}",),
        )
    materialized_node_count = 0

    def node_at(
        ordinal: int,
        _query: CompiledProgramInspectionQuery | None,
    ) -> CompiledProgramInspectionNode:
        nonlocal materialized_node_count
        materialized_node_count += 1
        return CompiledProgramInspectionNode(
            id=f"physical:event:{ordinal}",
            kind="placement",
            label=f"physical event {ordinal}",
            entity_ids=(f"q{ordinal}",),
            resource_ids=(f"channel-{ordinal % 64}",),
        )

    layer = CompiledProgramInspectionLayerIndex(
        id="physical",
        label="Physical placement",
        kind="physical",
        root_ids=(),
        nodes=CompiledProgramInspectionNodeIndex(
            node_count=node_count,
            node_at=node_at,
            ordinal_by_id=exact_ordinals.get,
            inverted_index=inverted.build(),
        ),
    )
    index_seconds = time.perf_counter() - index_started
    exact_node_id = f"physical:event:{node_count - 1}"
    exact_query = CompiledProgramInspectionQuery(
        layer_id="physical",
        snapshot_id="benchmark-inspection-index",
        node_id=exact_node_id,
        limit=1,
    )
    exact_started = time.perf_counter()
    exact_projection, exact_selection = layer.project(
        query=exact_query,
        default_limit=page_size,
        snapshot_id="benchmark-inspection-index",
    )
    exact_seconds = time.perf_counter() - exact_started
    exact_response_bytes = len(
        json.dumps(
            asdict(exact_projection), separators=(",", ":"), sort_keys=True
        ).encode()
    )

    materialized_node_count = 0
    filter_query = CompiledProgramInspectionQuery(
        layer_id="physical",
        snapshot_id="benchmark-inspection-index",
        kind="placement",
        resource_id="channel-63",
        limit=page_size,
    )
    filter_started = time.perf_counter()
    filter_projection, filter_selection = layer.project(
        query=filter_query,
        default_limit=page_size,
        snapshot_id="benchmark-inspection-index",
    )
    filter_seconds = time.perf_counter() - filter_started
    filter_response_bytes = len(
        json.dumps(
            asdict(filter_projection), separators=(",", ":"), sort_keys=True
        ).encode()
    )
    retained_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        **benchmark_record_header(
            case_id="inspection-index",
            case_version=1,
            kind="micro",
        ),
        "node_count": node_count,
        "page_size": page_size,
        "index_seconds": index_seconds,
        "exact_node_id": exact_node_id,
        "exact_query_seconds": exact_seconds,
        "exact_matching_count": exact_selection.page.matching_node_count,
        "exact_returned_count": len(exact_selection.nodes),
        "exact_response_bytes": exact_response_bytes,
        "filter_query_seconds": filter_seconds,
        "filter_matching_count": filter_selection.page.matching_node_count,
        "filter_returned_count": len(filter_selection.nodes),
        "filter_materialized_node_count": materialized_node_count,
        "filter_response_bytes": filter_response_bytes,
        "retained_bytes": retained_bytes,
        "peak_bytes": peak_bytes,
    }


def main() -> None:
    node_count, page_size = _options()
    print(
        BENCHMARK_RESULT_PREFIX
        + json.dumps(_benchmark(node_count, page_size), sort_keys=True)
    )


if __name__ == "__main__":
    main()

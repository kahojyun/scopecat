"""Measure the retained optimizer context for a long adaptive run."""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from collections import deque
from typing import cast

from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.measurements.points import AcceptedRunPoint, PointCandidate
from scopecat.optimization import (
    OPTIMIZER_DECISION_WINDOW,
    OPTIMIZER_OBSERVATION_WINDOW,
    CompletedPointObservation,
    PointOptimizerContext,
    PointProposalLedger,
)


def _decision_count() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", type=int, default=20_000)
    return cast("int", parser.parse_args().decisions)


def main() -> None:
    decision_count = _decision_count()
    if decision_count <= OPTIMIZER_DECISION_WINDOW:
        raise ValueError(
            f"decisions must exceed the {OPTIMIZER_DECISION_WINDOW}-decision window"
        )

    observations: deque[CompletedPointObservation] = deque(
        maxlen=OPTIMIZER_OBSERVATION_WINDOW
    )
    ledger = PointProposalLedger(initial_point_count=0)
    tracemalloc.start()
    started = time.perf_counter()
    for decision_index in range(decision_count):
        candidate = PointCandidate(
            {"x": float(decision_index)},
            source="optimizer",
            based_on_completed_point_count=ledger.accepted_count,
        )
        if decision_index < OPTIMIZER_OBSERVATION_WINDOW:
            point = AcceptedRunPoint.accept(
                candidate,
                logical_id=LogicalPointId(
                    PointDomainId("benchmark.adaptive", "points"),
                    ledger.next_logical_ordinal,
                ),
            )
            ledger = ledger.accept(candidate, point).recent()
            observations.append(CompletedPointObservation(point))
        else:
            ledger = ledger.reject(candidate, reason="benchmark retry").recent()

    completed_point_count = ledger.accepted_count
    context = PointOptimizerContext(
        observations=tuple(observations),
        ledger=ledger,
        point_limit=completed_point_count + 1,
        completed_point_count=completed_point_count,
    )
    retained_bytes, peak_bytes = tracemalloc.get_traced_memory()
    elapsed_seconds = time.perf_counter() - started
    tracemalloc.stop()

    result = {
        "schema": "scopecat.adaptive_optimizer_benchmark.v1",
        "decisions": context.ledger.decision_count,
        "accepted": context.completed_point_count,
        "rejected": context.ledger.rejected_count,
        "retained_decisions": len(context.ledger.entries),
        "retained_observations": len(context.observations),
        "decision_window": OPTIMIZER_DECISION_WINDOW,
        "observation_window": OPTIMIZER_OBSERVATION_WINDOW,
        "retained_bytes": retained_bytes,
        "peak_bytes": peak_bytes,
        "elapsed_seconds": elapsed_seconds,
    }
    print("ADAPTIVE_OPTIMIZER_BENCHMARK=" + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

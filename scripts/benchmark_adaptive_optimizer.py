"""Measure the retained optimizer context for a long adaptive run."""

from __future__ import annotations

import argparse
import gc
import json
import time
import tracemalloc
from collections import deque
from typing import cast

import numpy as np
import psutil

from scopecat.adaptive_domains import (
    AdaptiveRegion,
    DomainProposalAttempt,
    ResolvedDomainFragment,
)
from scopecat.execution.optimizer_observations import (
    project_completed_point_observation,
)
from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.points import AcceptedRunPoint, PointProposalAttempt
from scopecat.optimization import (
    OPTIMIZER_DECISION_WINDOW,
    OPTIMIZER_OBSERVATION_WINDOW,
    CompletedPointObservation,
    DomainOptimizerContext,
    DomainProposalLedger,
)
from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementRecord,
    MeasurementScalar,
)


def _options() -> tuple[int, int, int]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", type=int, default=20_000)
    parser.add_argument("--domain-points", type=int, default=1)
    parser.add_argument("--waveform-samples", type=int, default=32_768)
    options = parser.parse_args()
    return (
        cast("int", options.decisions),
        cast("int", options.domain_points),
        cast("int", options.waveform_samples),
    )


def main() -> None:
    decision_count, domain_points, waveform_samples = _options()
    if decision_count <= OPTIMIZER_DECISION_WINDOW:
        raise ValueError(
            f"decisions must exceed the {OPTIMIZER_DECISION_WINDOW}-decision window"
        )
    if waveform_samples <= 0:
        raise ValueError("waveform samples must be positive")
    if domain_points <= 0:
        raise ValueError("domain points must be positive")

    observations: deque[CompletedPointObservation] = deque(
        maxlen=OPTIMIZER_OBSERVATION_WINDOW
    )
    ledger = DomainProposalLedger(initial_point_count=0)
    process = psutil.Process()
    baseline_rss = cast("int", process.memory_info().rss)
    peak_rss = baseline_rss
    tracemalloc.start()
    started = time.perf_counter()
    for decision_index in range(decision_count):
        fragment = ResolvedDomainFragment.points(
            tuple(
                {"x": float(decision_index * domain_points + point_index)}
                for point_index in range(domain_points)
            )
        )
        proposal = DomainProposalAttempt(
            fragment,
            region_ids=("region-0",),
            source="optimizer",
            based_on_region_revisions={"region-0": decision_index},
        )
        candidate = PointProposalAttempt(
            {"x": float(decision_index)},
            source="optimizer",
            region_id="region-0",
            domain_proposal_fingerprint=proposal.proposal_fingerprint,
            based_on_region_revision=decision_index,
        )
        if decision_index < OPTIMIZER_OBSERVATION_WINDOW:
            point = AcceptedRunPoint.accept(
                candidate,
                logical_id=LogicalPointId(
                    PointDomainId("benchmark.adaptive", "points"),
                    ledger.point_count,
                ),
            )
            ledger = ledger.accept(proposal, (point,)).recent()
            raw_record = MeasurementRecord(
                run_id="benchmark-adaptive",
                logical_point_id=str(point.logical_id),
                point_index=point.ordinal,
                coordinates={},
                observables={
                    "score": MeasurementScalar.create(value=float(decision_index)),
                    "waveform": MeasurementArray.create(
                        values=np.full(
                            waveform_samples,
                            float(decision_index),
                            dtype=np.float64,
                        ),
                        unit="V",
                    ),
                },
            )
            observations.append(
                project_completed_point_observation(point, (raw_record,))
            )
            del raw_record
        else:
            ledger = ledger.reject(proposal, reason="benchmark retry").recent()
        peak_rss = max(peak_rss, cast("int", process.memory_info().rss))

    completed_point_count = ledger.accepted_point_count
    region = AdaptiveRegion(
        id="region-0",
        coordinates={},
        point_count=completed_point_count,
        completed_point_count=completed_point_count,
        revision=decision_count,
        point_limit=completed_point_count + 1,
    )
    context = DomainOptimizerContext(
        region=region,
        regions=(region,),
        observations=tuple(observations),
        ledger=ledger,
        total_point_limit=completed_point_count + 1,
        accepted_point_count=completed_point_count,
    )
    gc.collect()
    retained_bytes, peak_bytes = tracemalloc.get_traced_memory()
    retained_rss = cast("int", process.memory_info().rss)
    elapsed_seconds = time.perf_counter() - started
    tracemalloc.stop()

    result = {
        "schema": "scopecat.adaptive_optimizer_benchmark.v2",
        "decisions": context.ledger.decision_count,
        "accepted": context.accepted_point_count,
        "rejected": context.ledger.rejected_count,
        "retained_decisions": len(context.ledger.entries),
        "retained_observations": len(context.observations),
        "decision_window": OPTIMIZER_DECISION_WINDOW,
        "proposal_point_count": domain_points,
        "retained_fragment_payloads": sum(
            hasattr(entry.proposal, "fragment") for entry in context.ledger.entries
        ),
        "observation_window": OPTIMIZER_OBSERVATION_WINDOW,
        "waveform_samples": waveform_samples,
        "discarded_waveform_payload_bytes": (
            len(context.observations) * waveform_samples * np.dtype(np.float64).itemsize
        ),
        "retained_array_observables": sum(
            isinstance(value, MeasurementArray)
            for observation in context.observations
            for measurement in observation.measurements
            for value in measurement.observables.values()
        ),
        "omitted_array_observables": sum(
            len(measurement.omitted_array_ids)
            for observation in context.observations
            for measurement in observation.measurements
        ),
        "retained_bytes": retained_bytes,
        "peak_bytes": peak_bytes,
        "retained_rss_delta_bytes": max(retained_rss - baseline_rss, 0),
        "peak_rss_delta_bytes": max(peak_rss - baseline_rss, 0),
        "elapsed_seconds": elapsed_seconds,
    }
    print("ADAPTIVE_OPTIMIZER_BENCHMARK=" + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

"""backend batch modules."""

from __future__ import annotations

import scopecat as sc

from quantum_lab_demo.experiments.compute import build_backend_batch_job

_LOGICAL_POINTS = sc.input(
    "logical_points",
    sc.ScalarType(sc.IntType(minimum=1)),
)
_SEED = sc.input("seed", sc.ScalarType(sc.IntType(minimum=0)))
_BUILD_BACKEND_BATCH_JOB = sc.compute(
    "build-backend-batch-job",
    fn=build_backend_batch_job,
    output_type=sc.ScalarType(sc.PayloadType("backend_job")),
    inputs={
        "logical_points": _LOGICAL_POINTS,
        "seed": _SEED,
    },
)

BACKEND_BATCH_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.backend.batch",
    )
    .inputs(_LOGICAL_POINTS, _SEED)
    .resource(
        "readout",
        requires=("submit_backend_batch", "acquire_iq"),
    )
    .computes(_BUILD_BACKEND_BATCH_JOB)
    .bind_field(
        "readout",
        capability="submit_backend_batch",
        field="job",
        value=_BUILD_BACKEND_BATCH_JOB.output,
    )
    .bind_field(
        "readout",
        capability="acquire_iq",
        field="repetitions",
        value=_LOGICAL_POINTS * sc.Quantity(value=1.0, unit="count"),
    )
    .product(
        "backend_probabilities",
        resource="readout",
        unit="ratio",
        axes=(
            sc.record_axis(
                "backend_point",
                size=_LOGICAL_POINTS,
                kind="backend_point",
                unit="count",
            ),
        ),
    )
    .build()
)

__all__ = [
    "BACKEND_BATCH_MODULE",
]

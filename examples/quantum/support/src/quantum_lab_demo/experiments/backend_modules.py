"""backend batch modules."""

from __future__ import annotations

from typing import Annotated, cast

import scopecat as sc

from quantum_lab_demo.experiments.compute import build_backend_batch_job

_LOGICAL_POINTS_TYPE = sc.ScalarType(sc.IntType(minimum=1))
_SEED_TYPE = sc.ScalarType(sc.IntType(minimum=0))


@sc.module(id="quantum_lab_demo.experiments.backend.batch")
def BACKEND_BATCH_MODULE(
    logical_points: Annotated[sc.Input[int], _LOGICAL_POINTS_TYPE],
    seed: Annotated[sc.Input[int], _SEED_TYPE],
):
    logical_points_ref = cast("sc.ValueRef", logical_points)
    seed_ref = cast("sc.ValueRef", seed)
    build_job = sc.compute(
        "build-backend-batch-job",
        fn=build_backend_batch_job,
        output_type=sc.ScalarType(sc.PayloadType("backend_job")),
        inputs={
            "logical_points": logical_points_ref,
            "seed": seed_ref,
        },
    )
    return (
        sc.module_body()
        .resource(
            "readout",
            requires=("submit_backend_batch", "acquire_iq"),
        )
        .computes(build_job)
        .bind_field(
            "readout",
            capability="submit_backend_batch",
            field="job",
            value=build_job.output,
        )
        .bind_field(
            "readout",
            capability="acquire_iq",
            field="repetitions",
            value=logical_points_ref * sc.Quantity(value=1.0, unit="count"),
        )
        .product(
            "backend_probabilities",
            unit="ratio",
            axes=(
                sc.product_axis(
                    "backend_point",
                    size=logical_points_ref,
                    kind="backend_point",
                    unit="count",
                ),
            ),
        )
        .acquire(
            "read-backend-probabilities",
            "backend_probabilities",
            resource="readout",
            capability="acquire_iq",
        )
    )


__all__ = [
    "BACKEND_BATCH_MODULE",
]

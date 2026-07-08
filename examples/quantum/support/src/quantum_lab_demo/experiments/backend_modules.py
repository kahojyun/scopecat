"""backend batch modules."""

from __future__ import annotations

import scopecat as sc

from quantum_lab_demo.experiments.compute import build_backend_batch_job
from quantum_lab_demo.experiments.ids import BACKEND_BATCH_TEMPLATE_ID

BACKEND_BATCH_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.backend.batch",
        metadata={"template_id": BACKEND_BATCH_TEMPLATE_ID},
    )
    .input("logical_points", kind="count")
    .input("seed", kind="seed")
    .resource(
        "readout",
        requires=("submit_backend_batch", "acquire_iq"),
    )
    .compute(
        "build-backend-batch-job",
        fn=build_backend_batch_job,
        inputs={
            "logical_points": sc.input("logical_points"),
            "seed": sc.input("seed"),
        },
    )
    .bind_compute(
        "readout.submit_backend_batch.job",
        "build-backend-batch-job",
        kind="backend_job",
    )
    .bind("readout.acquire_iq.repetitions", sc.input("logical_points"))
    .as_module()
)

__all__ = [
    "BACKEND_BATCH_MODULE",
]

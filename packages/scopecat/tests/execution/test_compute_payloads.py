from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

from scopecat.execution.effects.boundary import EffectBoundary
from scopecat.execution.effects.compute import (
    ComputeEffectExecutor,
    EffectEvaluationFrame,
)
from scopecat.execution.local.program import ComputeOperation, OutputInput, PayloadSlot
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import (
    Array,
    ArrayDimension,
    Float,
    Payload,
    Scalar,
)
from scopecat.program.value_graph import ComputeOutput, OperationId, operation_result_id
from scopecat.sdk.payloads import PayloadCodec, PayloadCodecRegistry


def _operation() -> ComputeOperation:
    operation_id = "point.compute.program"
    return ComputeOperation(
        operation_id=operation_id,
        logical_compute_node_id="program",
        implementation_id="tests.program",
        kernel=lambda: {"program": 1},
        inputs={},
        result=ComputeOutput(
            id=operation_result_id(OperationId(SymbolId(local_id="program"))),
            value_type=Scalar(Payload("tests.program/v1")),
        ),
        payload_slot=PayloadSlot(
            id=f"{operation_id}.payload",
            schema_id="tests.program/v1",
        ),
    )


def _failing_encoder(_value: object) -> bytes:
    raise ValueError("test encoder rejected the program")


@pytest.mark.parametrize(
    "payload_codecs",
    [
        PayloadCodecRegistry(),
        PayloadCodecRegistry(
            {
                "tests.program/v1": PayloadCodec(
                    id="tests.failing",
                    version=1,
                    media_type="application/octet-stream",
                    encoder=_failing_encoder,
                    decoder=lambda content: content,
                )
            }
        ),
    ],
)
def test_payload_codec_resolution_and_encoding_fail_as_compute_operations(
    payload_codecs: PayloadCodecRegistry,
) -> None:
    boundary = EffectBoundary(
        run_id="payload-codec-failure",
    )
    executor = ComputeEffectExecutor(
        boundary=boundary,
        payload_codecs=payload_codecs,
    )
    frame = EffectEvaluationFrame()

    executor.execute(frame, (_operation(),))

    assert [problem.code for problem in boundary.problems] == [
        "compute_operation_failed"
    ]
    assert frame.compute_results == {}
    assert frame.payloads == {}


def test_compute_executor_normalizes_and_chains_array_results() -> None:
    trace_type = Array(
        dtype="float64",
        dimensions=(ArrayDimension("sample", 3),),
        unit="V",
    )
    trace_id = operation_result_id(OperationId(SymbolId(local_id="trace")))
    peak_id = operation_result_id(OperationId(SymbolId(local_id="peak")))
    boundary = EffectBoundary(
        run_id="array-compute",
    )
    executor = ComputeEffectExecutor(
        boundary=boundary,
        payload_codecs=PayloadCodecRegistry(),
    )
    frame = EffectEvaluationFrame()

    def peak(*, trace: NDArray[np.float64]) -> float:
        return float(np.max(trace))

    executor.execute(
        frame,
        (
            ComputeOperation(
                operation_id="point.compute.trace",
                logical_compute_node_id="trace",
                implementation_id="tests.trace",
                kernel=lambda: [1, 2, 3],
                inputs={},
                result=ComputeOutput(id=trace_id, value_type=trace_type),
            ),
            ComputeOperation(
                operation_id="point.compute.peak",
                logical_compute_node_id="peak",
                implementation_id="tests.peak",
                kernel=peak,
                inputs={
                    "trace": OutputInput(value_id=trace_id, value_type=trace_type),
                },
                result=ComputeOutput(
                    id=peak_id,
                    value_type=Scalar(Float()),
                ),
            ),
        ),
    )

    assert boundary.problems == []
    trace = frame.compute_results[trace_id]
    assert isinstance(trace, np.ndarray)
    assert trace.dtype == np.dtype("float64")
    assert trace.tolist() == [1.0, 2.0, 3.0]
    assert frame.compute_results[peak_id] == 3.0

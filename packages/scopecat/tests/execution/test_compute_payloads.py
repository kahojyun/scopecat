from __future__ import annotations

import pytest

from scopecat.execution.effects.compute import (
    ComputeEffectExecutor,
    EffectEvaluationFrame,
)
from scopecat.execution.effects.journaled import JournaledEffectBoundary
from scopecat.execution.local.program import ComputeOperation, PayloadSlot
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Payload, Scalar
from scopecat.program.value_graph import ComputeOutput, OperationId, operation_result_id
from scopecat.sdk.payloads import PayloadCodec, PayloadCodecRegistry
from tests.testkit.runtime import FakeExecutionJournal


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
    boundary = JournaledEffectBoundary(
        run_id="payload-codec-failure",
        journal=FakeExecutionJournal(),
    )
    executor = ComputeEffectExecutor(
        journal=boundary,
        payload_codecs=payload_codecs,
    )
    frame = EffectEvaluationFrame()

    executor.execute(frame, (_operation(),))

    assert [problem.code for problem in boundary.problems] == [
        "compute_operation_failed"
    ]
    assert frame.compute_results == {}
    assert frame.payloads == {}

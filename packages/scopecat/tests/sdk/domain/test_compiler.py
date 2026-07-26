from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import pytest

from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.measurements.points import RunPoint, RunPointContract
from scopecat.measurements.values import MeasurementValueCatalog
from scopecat.sdk.domain.compiler import (
    DomainBatchInputs,
    DomainBatchRequest,
    DomainResolvedInputs,
)
from scopecat.sdk.domain.view import (
    DomainCallView,
    DomainPointRef,
    DomainProgramView,
)


def _request() -> DomainBatchRequest:
    point_id = LogicalPointId(PointDomainId("experiment", "points"), 0)
    point = DomainPointRef(point_id.value, 0, point_id)
    run_point = RunPoint(point_id, {})
    return DomainBatchRequest(
        batch_ordinal=0,
        call=DomainCallView(
            id="call",
            program=DomainProgramView(
                id="program",
                dialect_id="tests",
                dialect_version="1",
                body=object(),
            ),
            results=(),
        ),
        inputs=DomainBatchInputs(
            program=DomainResolvedInputs((0,), ()),
            compiler=DomainResolvedInputs((0,), ()),
        ),
        points=(point,),
        measurement_catalog=MeasurementValueCatalog(
            RunPointContract("experiment", "tests", ()),
            (),
            (),
        ),
        run_points=(run_point,),
    )


def test_resolved_inputs_require_complete_aligned_columns() -> None:
    inputs = DomainResolvedInputs(
        ordinals=(0, 1),
        columns=(("x", (2, 3)),),
    )

    assert inputs.input("x") == (2, 3)
    with pytest.raises(KeyError):
        inputs.input("missing")
    with pytest.raises(ValueError, match="point count"):
        replace(inputs, columns=(("x", (2,)),))


def test_resolved_inputs_decode_each_collection_into_a_typed_value() -> None:
    inputs = DomainResolvedInputs(
        ordinals=(2, 4),
        columns=(("rows", (({"value": 1},), ({"value": 2}, {"value": 3}))),),
    )

    def decode(rows: Sequence[dict[str, int]]) -> tuple[int, ...]:
        return tuple(row["value"] for row in rows)

    assert inputs.decode_collection("rows", decode) == ((1,), (2, 3))


def test_batch_inputs_require_matching_program_and_compiler_points() -> None:
    with pytest.raises(ValueError, match="coverage"):
        DomainBatchInputs(
            program=DomainResolvedInputs((0,), ()),
            compiler=DomainResolvedInputs((1,), ()),
        )


def test_batch_request_requires_inputs_and_run_points_to_match_points() -> None:
    request = _request()

    with pytest.raises(ValueError, match="inputs"):
        replace(
            request,
            inputs=DomainBatchInputs(
                program=DomainResolvedInputs((1,), ()),
                compiler=DomainResolvedInputs((1,), ()),
            ),
        )
    with pytest.raises(ValueError, match="run points"):
        replace(request, run_points=())

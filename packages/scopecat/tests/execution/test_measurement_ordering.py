from __future__ import annotations

import pytest

from scopecat.execution.measurement_ordering import CanonicalMeasurementBuffer
from scopecat.records.measurement import MeasurementRecord


def _record(point_index: int) -> MeasurementRecord:
    return MeasurementRecord(
        run_id="run-1",
        logical_point_id=f"point-{point_index}",
        point_index=point_index,
        coordinates={},
        observables={},
    )


def test_measurement_buffer_releases_only_the_canonical_prefix() -> None:
    buffer = CanonicalMeasurementBuffer()

    assert buffer.add((_record(0),)) == (_record(0),)
    assert buffer.add((_record(2),)) == ()
    assert buffer.pending_indices == (2,)
    assert buffer.add((_record(1),)) == (_record(1), _record(2))
    assert buffer.pending_indices == ()
    assert buffer.next_index == 3


def test_measurement_buffer_rejects_duplicate_or_committed_points() -> None:
    buffer = CanonicalMeasurementBuffer()
    buffer.add((_record(1),))

    with pytest.raises(ValueError, match="already buffered"):
        buffer.add((_record(1),))

    buffer.add((_record(0),))
    with pytest.raises(ValueError, match="already buffered"):
        buffer.add((_record(0),))


def test_measurement_buffer_does_not_publish_through_an_illegal_block_cut() -> None:
    buffer = CanonicalMeasurementBuffer(
        next_index=2,
        is_durable_cut=lambda point_count: point_count in (2, 6),
    )

    assert buffer.add((_record(2), _record(5))) == ()
    assert buffer.pending_indices == (2, 5)
    assert buffer.add((_record(4), _record(3))) == tuple(
        _record(index) for index in range(2, 6)
    )
    assert buffer.next_index == 6

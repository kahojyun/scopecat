from __future__ import annotations

import numpy as np
import pytest

from scopecat.execution.measurement_ordering import (
    CanonicalMeasurementBuffer,
    MeasurementChunkBuffer,
)
from scopecat.records.measurement import MeasurementArray, MeasurementRecord


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


def test_measurement_chunk_buffer_releases_bounded_chunks_and_final_tail() -> None:
    buffer = MeasurementChunkBuffer(record_limit=3)

    assert buffer.add((_record(0), _record(1))) == ()
    assert buffer.pending_count == 2
    assert buffer.add((_record(2), _record(3), _record(4), _record(5))) == (
        (_record(0), _record(1), _record(2)),
        (_record(3), _record(4), _record(5)),
    )
    assert buffer.pending_count == 0
    assert buffer.add((_record(6),)) == ()
    assert buffer.finish() == ((_record(6),),)
    assert buffer.pending_count == 0


def test_measurement_chunk_buffer_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        MeasurementChunkBuffer(record_limit=0)
    with pytest.raises(ValueError, match="must be positive"):
        MeasurementChunkBuffer(value_byte_limit=0)


def test_measurement_chunk_buffer_releases_large_waveforms_by_value_bytes() -> None:
    buffer = MeasurementChunkBuffer(record_limit=100, value_byte_limit=24)
    records = tuple(
        MeasurementRecord(
            run_id="run-1",
            point_index=index,
            coordinates={},
            observables={
                "waveform": MeasurementArray.create(
                    values=np.arange(2, dtype=np.float64),
                )
            },
        )
        for index in range(3)
    )

    assert buffer.add(records) == ((records[0],), (records[1],))
    assert buffer.pending_count == 1
    assert buffer.pending_value_bytes == 16
    assert buffer.finish() == ((records[2],),)

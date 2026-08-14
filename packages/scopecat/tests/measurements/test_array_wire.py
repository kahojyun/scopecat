from __future__ import annotations

import numpy as np
import pytest

from scopecat.measurements.array_wire import (
    MeasurementArrayWireError,
    decode_measurement_array,
    encode_measurement_array,
)
from scopecat.records.measurement import MeasurementArray


def test_numeric_wire_round_trip_reuses_immutable_array_storage() -> None:
    original = MeasurementArray.create(
        values=np.arange(100_000, dtype=np.float64),
        unit="V",
    )

    content = encode_measurement_array(original)
    restored = decode_measurement_array(
        content,
        dtype="float64",
        unit="V",
        shape=original.shape,
        metadata={},
    )

    assert isinstance(content, memoryview)
    assert np.shares_memory(restored.values, original.values)
    assert not restored.values.flags.writeable


def test_bool_wire_round_trip_reuses_immutable_array_storage() -> None:
    original = MeasurementArray.create(
        values=np.asarray([True, False, True], dtype=np.bool_),
        dtype="bool",
    )

    restored = decode_measurement_array(
        encode_measurement_array(original),
        dtype="bool",
        unit=None,
        shape=original.shape,
        metadata={},
    )

    assert np.shares_memory(restored.values, original.values)
    assert restored.values.tolist() == [True, False, True]


def test_wire_decode_still_rejects_non_finite_numeric_values() -> None:
    content = np.asarray([np.inf], dtype="<f8").tobytes()

    with pytest.raises(MeasurementArrayWireError, match="payload"):
        decode_measurement_array(
            content,
            dtype="float64",
            unit=None,
            shape=(1,),
            metadata={},
        )

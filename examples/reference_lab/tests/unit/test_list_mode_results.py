from __future__ import annotations

from ._list_mode_test_support import (
    MeasurementArray,
    MeasurementPartitionedArray,
    np,
    realize_integrated_iq_chunks,
    realize_integrated_iq_value,
)


def test_list_mode_logical_result_preserves_partial_shot_availability() -> None:
    value = realize_integrated_iq_value(
        np.asarray([1 + 2j, 0j, 3 + 4j], dtype=np.complex128),
        np.asarray([True, False, True], dtype=np.bool_),
    )

    assert isinstance(value, MeasurementArray)
    assert value.availability is not None
    assert value.availability.valid.tolist() == [True, False, True]
    [failure] = value.availability.unavailable
    assert failure.reason == "missing"
    assert failure.flat_indices == (1,)


def test_list_mode_logical_result_preserves_entity_by_shot_shape() -> None:
    value = realize_integrated_iq_value(
        np.asarray(
            [[1 + 2j, 3 + 4j], [5 + 6j, 0j]],
            dtype=np.complex128,
        ),
        np.asarray([[True, True], [True, False]], dtype=np.bool_),
    )

    assert isinstance(value, MeasurementArray)
    assert value.values.shape == (2, 2)
    assert value.availability is not None
    assert value.availability.valid.tolist() == [[True, True], [True, False]]


def test_list_mode_logical_result_preserves_shot_partitions() -> None:
    value = realize_integrated_iq_chunks(
        (
            np.asarray([1 + 2j, 3 + 4j], dtype=np.complex128),
            np.asarray([0j, 5 + 6j, 7 + 8j], dtype=np.complex128),
        ),
        (
            np.asarray([True, True], dtype=np.bool_),
            np.asarray([False, True, True], dtype=np.bool_),
        ),
    )

    assert isinstance(value, MeasurementPartitionedArray)
    assert value.axis == 0
    assert [partition.shape for partition in value.partitions] == [(2,), (3,)]
    assert value.shape == (5,)
    assert value.availability is not None
    assert value.availability.valid.tolist() == [True, True, False, True, True]

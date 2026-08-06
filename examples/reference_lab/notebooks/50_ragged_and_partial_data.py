"""Inspect ragged, unavailable, and partially completed measurement data."""

from __future__ import annotations

# %%
import scopecat as sc
from scopecat.kernel.errors import RunFailed
from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementUnavailable,
    MeasurementValue,
)

from reference_lab.configuration import EXAMPLE_ROOT
from reference_lab.workflows.event_capture import ragged_event_capture


def available_shape(value: MeasurementValue) -> list[int] | None:
    if isinstance(value, MeasurementUnavailable):
        return None
    assert isinstance(value, MeasurementArray)
    return list(value.shape)


# %%
with sc.open_project(EXAMPLE_ROOT).connect(operator="gallery") as lab:
    invocation = ragged_event_capture()
    ragged_run = lab.run(
        invocation,
        name="Ragged event capture",
        tags=("gallery", "ragged", "unavailable"),
    )
    ragged = ragged_run.measurements()
    signal_view = ragged[invocation.output.signal]
    sample_dimension = signal_view.dims[1]
    signal_id = signal_view.id
    available_ragged = ragged.where(signal_view.is_available())
    ragged_window = available_ragged.isel_ragged(
        {sample_dimension: slice(0, 2)},
        variable=signal_id,
    )

    failing = invocation.points(
        (
            {invocation.output.event_count: 2.0},
            {invocation.output.event_count: -1.0},
            {invocation.output.event_count: 4.0},
        )
    )
    try:
        lab.run(
            failing,
            name="Partial event capture",
            tags=("gallery", "partial", "failure"),
        )
    except RunFailed as error:
        partial_run = lab.get_run(error.run_id)
    else:
        raise AssertionError("the deterministic failure point must stop the run")
    partial = partial_run.measurements()
    partial_status = partial_run.manifest.status

ragged_summary = {
    "ragged_shapes": [
        available_shape(value) for value in ragged[invocation.output.signal].raw_values
    ],
    "window_shapes": [
        available_shape(value)
        for value in ragged_window[invocation.output.signal].raw_values
    ],
    "partial_status": partial_status,
    "partial_records": len(partial),
    "expected_records": partial.metadata["expected_record_count"],
}
print(ragged_summary)

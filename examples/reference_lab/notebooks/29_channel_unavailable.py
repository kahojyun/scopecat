"""Keep q0 data when the q1 demodulation channel is unavailable."""

from __future__ import annotations

# %%
import scopecat as sc
from scopecat.records.measurement import MeasurementUnavailable

from reference_lab.configuration import EXAMPLE_ROOT
from reference_lab.workflows.ramsey_experiments import parallel_raw_ramsey

# %%
with sc.open_project(EXAMPLE_ROOT).connect(operator="gallery") as lab:
    invocation = parallel_raw_ramsey()
    run = lab.run(
        invocation,
        name="One unavailable demodulation channel",
        tags=("gallery", "multi-channel", "unavailable"),
    )
    data = run.measurements()
    q0 = data[invocation.output.q0_iq]
    q1 = data[invocation.output.q1_iq]
    q1_available = data.where(q1.is_available())

channel_unavailable_summary = {
    "records": len(data),
    "q0_unavailable": sum(
        isinstance(value, MeasurementUnavailable) for value in q0.raw_values
    ),
    "q1_unavailable": sum(
        isinstance(value, MeasurementUnavailable) for value in q1.raw_values
    ),
    "q1_available_records": len(q1_available),
}
print(channel_unavailable_summary)

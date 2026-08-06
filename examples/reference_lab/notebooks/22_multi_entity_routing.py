"""Acquire entity-aligned results through one symbolic instrument group."""

from __future__ import annotations

# %%
import scopecat as sc

from reference_lab.configuration import EXAMPLE_ROOT
from reference_lab.workflows.multi_entity_temperature import (
    multi_entity_temperature,
)

# %%
with sc.open_project(EXAMPLE_ROOT).connect(operator="gallery") as lab:
    invocation = multi_entity_temperature()
    preview = lab.preview(invocation)
    run = lab.run(
        invocation,
        name="Multi-entity temperature sample",
        tags=("gallery", "multi-entity", "routing"),
    )
    data = run.measurements()
    q0 = data[invocation.output.q0_temperature].require_quantities("K")
    q1 = data[invocation.output.q1_temperature].require_quantities("K")

multi_entity_summary = {
    "point_count": preview.point_count,
    "record_count": len(data),
    "q0_samples": len(q0),
    "q1_samples": len(q1),
    "variables": sorted(data.data_vars),
}
print(multi_entity_summary)

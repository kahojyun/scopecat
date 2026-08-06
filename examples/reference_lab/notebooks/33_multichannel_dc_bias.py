"""Bias four qubits through two two-channel DC sources."""

from __future__ import annotations

import scopecat as sc

from reference_lab.configuration import EXAMPLE_ROOT
from reference_lab.workflows.multichannel_bias import (
    MULTICHANNEL_DC_BIAS,
    OPERATE_PROFILE,
)

# %%
with sc.open_project(EXAMPLE_ROOT).connect(operator="gallery") as lab:
    config = lab.resolve_config()
    flux_routes = [
        binding
        for binding in config.routing.bindings
        if binding.interface_id == "scopecat.dc_source/v3"
        and binding.entity_id is not None
    ]
    run = lab.run(MULTICHANNEL_DC_BIAS)
    data = run.measurements()
    status = run.manifest.status

physical_bias_mv = {
    entity.id: round(data[record].require_quantities("mV")[0].value, 6)
    for entity, record in MULTICHANNEL_DC_BIAS.output.physical_bias.items()
}
readback_mv = {
    entity.id: round(data[records.actual_voltage].require_quantities("mV")[0].value, 6)
    for entity, records in MULTICHANNEL_DC_BIAS.output.readback.items()
}
settled = {
    entity.id: data[records.settled].require_values()[0]
    for entity, records in MULTICHANNEL_DC_BIAS.output.readback.items()
}

multichannel_dc_bias_summary = {
    "devices": sorted({binding.instrument_id for binding in flux_routes}),
    "routes": {
        binding.entity_id: (binding.instrument_id, binding.channel_id)
        for binding in flux_routes
    },
    "profile": OPERATE_PROFILE,
    "physical_bias_mv": physical_bias_mv,
    "readback_mv": readback_mv,
    "settled": settled,
    "records": len(data),
    "status": status,
}
print(multichannel_dc_bias_summary)

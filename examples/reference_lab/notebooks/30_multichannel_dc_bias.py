"""Bias four qubits through two two-channel DC sources."""

from __future__ import annotations

import scopecat as sc

from reference_lab.configuration import EXAMPLE_ROOT
from reference_lab.workflows.multichannel_bias import MULTICHANNEL_DC_BIAS

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

multichannel_dc_bias_summary = {
    "devices": sorted({binding.instrument_id for binding in flux_routes}),
    "routes": {
        binding.entity_id: (binding.instrument_id, binding.channel_id)
        for binding in flux_routes
    },
    "records": len(data),
    "status": status,
}
print(multichannel_dc_bias_summary)

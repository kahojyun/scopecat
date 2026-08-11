"""Bias four qubits through two two-channel DC sources."""

from __future__ import annotations

import scopecat as sc

from reference_lab.configuration import EXAMPLE_ROOT
from reference_lab.notebook import show
from reference_lab.workflows.multichannel_bias import (
    MULTICHANNEL_DC_BIAS,
    OPERATE_PROFILE,
)

# %%
with sc.open_project(EXAMPLE_ROOT).connect(operator="gallery") as lab:
    config = lab.resolve_config()
    flux_routes = [
        (route.instrument_id, endpoint)
        for route in config.routing.routes
        for endpoint in route.endpoints
        if endpoint.interface_id == "scopecat.dc_source/v3"
        and endpoint.entity_id is not None
    ]
    run = lab.run(MULTICHANNEL_DC_BIAS)
    data = run.measurements()
    physical_bias_mv = {
        entity.id: round(data[record].require_quantities("mV")[0].value, 6)
        for entity, record in MULTICHANNEL_DC_BIAS.output.physical_bias.items()
    }
    readback_mv = {
        entity.id: round(
            data[records.actual_voltage].require_quantities("mV")[0].value,
            6,
        )
        for entity, records in MULTICHANNEL_DC_BIAS.output.readback.items()
    }
    settled = {
        entity.id: data[records.settled].require_values()[0]
        for entity, records in MULTICHANNEL_DC_BIAS.output.readback.items()
    }
    record_count = len(data)
    status = run.manifest.status

multichannel_dc_bias_summary = {
    "devices": sorted({instrument_id for instrument_id, _endpoint in flux_routes}),
    "routes": {
        endpoint.entity_id: (instrument_id, endpoint.channel_id)
        for instrument_id, endpoint in flux_routes
    },
    "profile": OPERATE_PROFILE,
    "physical_bias_mv": physical_bias_mv,
    "readback_mv": readback_mv,
    "settled": settled,
    "records": record_count,
    "status": status,
}
show(multichannel_dc_bias_summary)

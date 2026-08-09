"""Inspect the stable four-qubit signal and DC channel map."""

from __future__ import annotations

# %%
import scopecat as sc

from reference_lab.configuration import EXAMPLE_ROOT

# %%
with sc.open_project(EXAMPLE_ROOT).connect(operator="gallery") as lab:
    config = lab.resolve_config()
    quantum_routes = [
        (route.instrument_id, endpoint)
        for route in config.routing.routes
        for endpoint in route.endpoints
        if route.instrument_id in {"drive-stack", "readout-stack"}
    ]

channel_map_summary = {
    "drive": {
        endpoint.entity_id: endpoint.channel_id
        for _instrument_id, endpoint in quantum_routes
        if endpoint.interface_id == "quantum_lab.play_pulse_program/v1"
    },
    "readout": {
        endpoint.entity_id: endpoint.channel_id
        for _instrument_id, endpoint in quantum_routes
        if endpoint.interface_id == "quantum_lab.readout_pulse/v1"
    },
    "acquisition": {
        endpoint.entity_id: endpoint.channel_id
        for _instrument_id, endpoint in quantum_routes
        if endpoint.interface_id == "quantum_lab.acquire_iq/v1"
    },
    "flux": {
        endpoint.entity_id: (route.instrument_id, endpoint.channel_id)
        for route in config.routing.routes
        for endpoint in route.endpoints
        if endpoint.interface_id == "scopecat.dc_source/v3"
        and endpoint.entity_id is not None
    },
}
print(channel_map_summary)

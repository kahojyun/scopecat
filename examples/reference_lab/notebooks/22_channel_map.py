"""Inspect the stable four-qubit signal and DC channel map."""

from __future__ import annotations

# %%
import scopecat as sc

from reference_lab.configuration import EXAMPLE_ROOT

# %%
with sc.open_project(EXAMPLE_ROOT).connect(operator="gallery") as lab:
    config = lab.resolve_config()
    quantum_routes = [
        (route.role_id, route.instrument_id, endpoint)
        for route in config.routing.routes
        for endpoint in route.endpoints
        if route.instrument_id in {"drive-awg", "readout-awg", "readout-digitizer"}
        and endpoint.entity_id is not None
        and endpoint.channel_id is not None
    ]

channel_map_summary = {
    "drive": {
        entity_id: {
            quadrature: next(
                endpoint.channel_id
                for role_id, _instrument_id, endpoint in quantum_routes
                if role_id == role and endpoint.entity_id == entity_id
            )
            for quadrature, role in (("i", "drive-i"), ("q", "drive-q"))
        }
        for entity_id in ("q0", "q1", "q2", "q3")
    },
    "readout": {
        entity_id: {
            quadrature: next(
                endpoint.channel_id
                for role_id, _instrument_id, endpoint in quantum_routes
                if role_id == role and endpoint.entity_id == entity_id
            )
            for quadrature, role in (("i", "readout-i"), ("q", "readout-q"))
        }
        for entity_id in ("q0", "q1", "q2", "q3")
    },
    "acquisition": {
        endpoint.entity_id: endpoint.channel_id
        for role_id, _instrument_id, endpoint in quantum_routes
        if role_id == "readout-acquisition"
        and endpoint.interface_id == "reference_lab.digitizer_input/v1"
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

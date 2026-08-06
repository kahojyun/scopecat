"""Inspect the stable four-qubit signal and DC channel map."""

from __future__ import annotations

# %%
import scopecat as sc

from reference_lab.configuration import EXAMPLE_ROOT

# %%
with sc.open_project(EXAMPLE_ROOT).connect(operator="gallery") as lab:
    config = lab.resolve_config()
    quantum_routes = [
        binding
        for binding in config.routing.bindings
        if binding.instrument_id in {"drive-stack", "readout-stack"}
    ]

channel_map_summary = {
    "drive": {
        binding.entity_id: binding.channel_id
        for binding in quantum_routes
        if binding.interface_id == "quantum_lab.play_pulse_program/v1"
    },
    "readout": {
        binding.entity_id: binding.channel_id
        for binding in quantum_routes
        if binding.interface_id == "quantum_lab.readout_pulse/v1"
    },
    "acquisition": {
        binding.entity_id: binding.channel_id
        for binding in quantum_routes
        if binding.interface_id == "quantum_lab.acquire_iq/v1"
    },
    "flux": {
        binding.entity_id: (binding.instrument_id, binding.channel_id)
        for binding in config.routing.bindings
        if binding.interface_id == "scopecat.dc_source/v3"
        and binding.entity_id is not None
    },
}
print(channel_map_summary)

"""Exercise coupled virtual devices through the normal notebook API."""

from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat_instruments.interfaces import DC_SOURCE, NETWORK_SWEEP

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# %%
with sc.open_project(PROJECT_ROOT).connect(operator="notebook-demo") as lab:
    inventory = [
        (item.instrument_id, item.availability) for item in lab.instruments.list().items
    ]

    with lab.instruments.open(
        "flux-source",
        "mixing-chamber",
        "readout-vna",
    ) as instruments:
        instruments.apply(
            DC_SOURCE,
            {
                "source_mode": "voltage",
                "voltage_level": sc.Quantity(0.05, "V"),
                "output_enabled": True,
            },
            instrument_id="flux-source",
        )
        try:
            temperature = instruments.read_state("mixing-chamber")
            instruments.apply(
                NETWORK_SWEEP,
                {
                    "start_frequency": sc.Quantity(4.8, "GHz"),
                    "stop_frequency": sc.Quantity(5.2, "GHz"),
                    "points": 201,
                },
                instrument_id="readout-vna",
            )
            trace = instruments.collect(
                NETWORK_SWEEP,
                "sweep",
                "frequency",
                "s_parameter",
                instrument_id="readout-vna",
            )
            trace_results = (
                {
                    name: value.model_dump(mode="json", include={"shape"})
                    for name, value in trace.readback.values.items()
                }
                if trace.readback is not None
                else {}
            )
        finally:
            instruments.apply(
                DC_SOURCE,
                {"output_enabled": False},
                instrument_id="flux-source",
            )

print("inventory:", inventory)
print(
    "temperature:",
    {
        f"{property_state.interface_id}.{property_state.property_id}": (
            property_state.value.root
        )
        for property_state in temperature.properties
    },
)
print(
    "trace:",
    {
        "status": trace.status,
        "results": trace_results,
    },
)

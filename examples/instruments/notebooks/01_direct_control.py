"""Exercise coupled virtual devices through the normal notebook API."""

from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat_instruments.members import (
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE_LEVEL,
    NETWORK_SWEEP_ACQUISITION,
    NETWORK_SWEEP_FREQUENCY_RESULT,
    NETWORK_SWEEP_POINTS,
    NETWORK_SWEEP_S_PARAMETER_RESULT,
    NETWORK_SWEEP_START_FREQUENCY,
    NETWORK_SWEEP_STOP_FREQUENCY,
)

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
            {
                DC_SOURCE_MODE: "voltage",
                DC_SOURCE_VOLTAGE_LEVEL: sc.Quantity(0.05, "V"),
                DC_SOURCE_OUTPUT_ENABLED: True,
            },
            instrument_id="flux-source",
        )
        try:
            temperature = instruments.read_state("mixing-chamber")
            instruments.apply(
                {
                    NETWORK_SWEEP_START_FREQUENCY: sc.Quantity(4.8, "GHz"),
                    NETWORK_SWEEP_STOP_FREQUENCY: sc.Quantity(5.2, "GHz"),
                    NETWORK_SWEEP_POINTS: 201,
                },
                instrument_id="readout-vna",
            )
            trace = instruments.collect(
                NETWORK_SWEEP_ACQUISITION,
                NETWORK_SWEEP_FREQUENCY_RESULT,
                NETWORK_SWEEP_S_PARAMETER_RESULT,
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
                {DC_SOURCE_OUTPUT_ENABLED: False},
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

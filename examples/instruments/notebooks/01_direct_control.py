"""Exercise coupled virtual devices through the normal notebook API."""

from __future__ import annotations

from pathlib import Path

import scopecat as sc

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# %%
with sc.open_project(PROJECT_ROOT).connect(operator="notebook-demo") as lab:
    inventory = [
        (item.spec.id, item.availability) for item in lab.instruments.list().items
    ]

    with lab.instruments.open(
        "flux-source",
        "mixing-chamber",
        "readout-vna",
    ) as instruments:
        instruments.apply(
            "dc_output",
            {
                "voltage_level": sc.Quantity(0.05, "V"),
                "output_enabled": True,
            },
            instrument_id="flux-source",
        )
        try:
            temperature = instruments.read_state("mixing-chamber")
            instruments.apply(
                "network_sweep",
                {
                    "start_frequency": sc.Quantity(4.8, "GHz"),
                    "stop_frequency": sc.Quantity(5.2, "GHz"),
                    "points": 201,
                },
                instrument_id="readout-vna",
            )
            trace = instruments.collect(
                "network_sweep",
                "frequency",
                "s_parameter",
                instrument_id="readout-vna",
            )
            trace_products = (
                {
                    name: value.model_dump(mode="json", include={"shape"})
                    for name, value in trace.readback.values.items()
                }
                if trace.readback is not None
                else {}
            )
        finally:
            instruments.apply(
                "dc_output",
                {"output_enabled": False},
                instrument_id="flux-source",
            )

print("inventory:", inventory)
print(
    "temperature:",
    {
        f"{field.capability_id}.{field.field_path}": field.value.root
        for field in temperature.fields
    },
)
print(
    "trace:",
    {
        "status": trace.status,
        "products": trace_products,
    },
)

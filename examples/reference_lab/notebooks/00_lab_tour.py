"""Inspect the shared inventory, routing context, and parameter tables."""

from __future__ import annotations

# %%
import scopecat as sc
from scopecat.records.parameter import TableParameterValue

from reference_lab.configuration import EXAMPLE_ROOT

# %%
with sc.open_project(EXAMPLE_ROOT).connect(operator="gallery") as lab:
    inventory = lab.instruments.list().items
    config = lab.resolve_config()
    parameter_tables = {
        definition.id: config.parameter_snapshot.get(definition.id)
        for definition in config.parameter_catalog.definitions
    }

lab_tour_summary = {
    "instruments": [item.instrument_id for item in inventory],
    "availability": {item.instrument_id: item.availability for item in inventory},
    "parameter_rows": {
        table_id: len(value.rows)
        for table_id, value in parameter_tables.items()
        if isinstance(value, TableParameterValue)
    },
}
print(lab_tour_summary)

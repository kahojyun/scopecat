"""Notebook-style example: open the demo project and connect its daemon."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import EXAMPLE_ROOT

# %%
project = sc.open_project(EXAMPLE_ROOT)
lab = project.connect()

# %%
system = lab.resolve_config().system
summary = {
    "project": project.root.name,
    "daemon_project": lab.health().project_id,
    "run_count": len(lab.runs()),
    "primary_entity": system.primary_entity_id,
    "entities": [entity.id for entity in system.topology.entities],
    "channels": list(
        dict.fromkeys(
            binding.channel_id
            for binding in system.routing.bindings
            if binding.channel_id is not None
        )
    ),
    "routing_instruments": list(
        dict.fromkeys(binding.instrument_id for binding in system.routing.bindings)
    ),
}
print(summary)

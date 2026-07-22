"""Notebook-style example: open the demo lab workspace."""

from __future__ import annotations

# %%
from quantum_lab_demo import notebook_workspace, quantum_lab

# %%
workspace = notebook_workspace("01-open-workspace")
lab = quantum_lab(workspace=workspace)

# %%
system = lab.resolve_config().system
summary = {
    "workspace": lab.workspace,
    "run_count": len(lab.runs()),
    "primary_entity": system.primary_entity_id,
    "entities": [entity.id for entity in system.topology.entities],
    "lines": [line.id for line in system.topology.lines],
    "routing_instruments": list(
        dict.fromkeys(binding.instrument_id for binding in system.routing.bindings)
    ),
}
print(summary)

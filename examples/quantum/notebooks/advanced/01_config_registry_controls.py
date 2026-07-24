"""Advanced: inspect explicit config registration, activation, and CAS."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import EXAMPLE_ROOT

# %%
lab = sc.open_project(EXAMPLE_ROOT).connect()

# %%
# Ordinary notebook code can call lab.config.set_default(). This lower-level
# path is useful when an operator needs to inspect each registry transition.
draft = lab.config.edit().replace_scalar(
    "repetitions",
    sc.Quantity(256, "count"),
)
draft.table("qubits").update(
    key={"qubit": sc.EntityRef(id="q0", kind="logical_qubit")},
    values={"drive_frequency": sc.Quantity(5.05, "GHz")},
)
preview = lab.config.preview(
    draft,
    candidate_id="advanced-config-edit",
)
if not preview.valid:
    raise RuntimeError(f"config draft is invalid: {preview.problems}")

# %%
entry_id = f"advanced-config-edit-g{preview.base_generation}"
registered = lab.config.register(
    draft,
    preview=preview,
    entry_id=entry_id,
    note="inspect the explicit registry workflow",
)
activated = lab.config.activate_entry(
    registered.entry.id,
    expected_generation=preview.base_generation,
    note="select the explicitly registered revision",
)
rolled_back = lab.config.rollback(
    expected_generation=activated.active_state.generation,
    note="restore the configuration active before this example",
)

# %%
advanced_registry_summary = {
    "base_entry": preview.base_entry.id,
    "registered_entry": registered.entry.id,
    "changed_parameters": [delta.parameter_id for delta in preview.deltas],
    "activated_generation": activated.active_state.generation,
    "restored_entry": rolled_back.active_state.active_entry_id,
    "rollback_generation": rolled_back.active_state.generation,
}
print(advanced_registry_summary)

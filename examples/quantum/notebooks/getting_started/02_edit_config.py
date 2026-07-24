"""Notebook-style example: edit, review, activate, and roll back active config."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import EXAMPLE_ROOT

# %%
lab = sc.open_project(EXAMPLE_ROOT).connect()

# %%
# Draft state stays in this Python process. Edits remain typed: scalar
# replacement and a keyed table-cell update use the same value objects as
# experiment authoring.
draft = lab.edit_config().replace_scalar(
    "repetitions",
    sc.Quantity(256, "count"),
)
draft.table("qubits").update(
    key={"qubit": sc.EntityRef(id="q0", kind="logical_qubit")},
    values={"drive_frequency": sc.Quantity(5.05, "GHz")},
)

# %%
# Preview validates against the currently active entry without writing anything.
preview = lab.preview_config_draft(
    draft,
    candidate_id="getting-started-config-edit",
)
if not preview.valid:
    raise RuntimeError(f"config draft is invalid: {preview.problems}")

# %%
# A generation-derived id avoids collisions when this example is run repeatedly.
entry_id = f"getting-started-config-edit-g{preview.base_generation}"
registered = lab.register_config_draft(
    draft,
    preview=preview,
    entry_id=entry_id,
    note="typed edit from the getting-started example",
)

# %%
activated = lab.activate_config_entry(
    registered.entry.id,
    expected_generation=preview.base_generation,
    note="inspect the edited configuration",
)
rolled_back = lab.rollback(
    expected_generation=activated.active_state.generation,
    note="restore the configuration active before this example",
)

# %%
summary = {
    "base_entry": preview.base_entry.id,
    "registered_entry": registered.entry.id,
    "changed_parameters": [delta.parameter_id for delta in preview.deltas],
    "activated_generation": activated.active_state.generation,
    "rolled_back_entry": rolled_back.active_state.active_entry_id,
    "rollback_generation": rolled_back.active_state.generation,
}
print(summary)

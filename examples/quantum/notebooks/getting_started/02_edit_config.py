"""Notebook-style example: edit the default config and undo the change."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import EXAMPLE_ROOT

# %%
lab = sc.open_project(EXAMPLE_ROOT).connect()

# %%
# Draft state stays in this Python process. Scalar replacement and a keyed
# table-cell update use the same typed values as experiment authoring.
draft = lab.edit_config().replace_scalar(
    "repetitions",
    sc.Quantity(256, "count"),
)
draft.table("qubits").update(
    key={"qubit": sc.EntityRef(id="q0", kind="logical_qubit")},
    values={"drive_frequency": sc.Quantity(5.05, "GHz")},
)

# %%
# This one intent saves an immutable revision and makes it the new default.
# Validation, registry ids, and concurrency generations stay inside the client
# and daemon.
changed = lab.config.set_default(
    draft,
    note="typed edit from the getting-started example",
)

# Undo restores the previous distinct default while preserving both revisions
# and the activation history.
restored = lab.config.undo(
    note="restore the default active before this example",
)

# %%
summary = {
    "changed_parameters": [delta.parameter_id for delta in changed.deltas],
    "default_changed": (changed.entry.content_hash == changed.result_content_hash),
    "default_restored": (
        restored.active_state.active_entry_content_hash
        == changed.activation.previous_entry_content_hash
    ),
    "history_events": len(restored.active_state.history),
}
print(summary)

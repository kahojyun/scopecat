"""Notebook-style example: system-scale and backend-shaped cases."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.experiments import (
    BACKEND_BATCH_TEMPLATE,
    TOY_SURFACE_CODE_ROUND_TEMPLATE,
)

# %%
workspace = notebook_workspace("09-system-scale-cases")
lab = quantum_lab(workspace=workspace)

# %%
surface_code_preview = (
    lab.prepare(TOY_SURFACE_CODE_ROUND_TEMPLATE)
    .input("rounds", sc.Quantity(value=2.0, unit="count"))
    .preview(
        name="system-scale toy surface-code round",
        tags=("surface-code", "system"),
        description="small stabilizer schedule with round and entity axes",
    )
)

# %%
backend_batch_preview = (
    lab.prepare(BACKEND_BATCH_TEMPLATE)
    .inputs(logical_points=sc.Quantity(value=4.0, unit="count"), seed=5)
    .preview(
        name="system-scale backend batch",
        tags=("backend", "system"),
        description=(
            "one logical run point containing backend logical points and return order"
        ),
    )
)

# %%
system_scale_summary = {
    "surface_code_records": [record.id for record in surface_code_preview.records],
    "surface_code_coordinates": list(surface_code_preview.coordinate_ids),
    "backend_batch_payloads": [
        payload.node_id for payload in backend_batch_preview.payloads
    ],
    "backend_batch_records": [record.id for record in backend_batch_preview.records],
}
print(system_scale_summary)

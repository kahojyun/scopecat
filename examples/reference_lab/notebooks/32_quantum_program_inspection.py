"""Inspect the authored quantum structure before placing or running it."""

from __future__ import annotations

from reference_lab.notebook import show

# %%
from reference_lab.workflows.drag_beta_calibration import drag_beta_program

program_description = drag_beta_program.describe()
program_tree = drag_beta_program.draw()

program_inspection_summary = {
    "program_id": "drag-beta-rough-calibration",
    "description_has_ports": "ports:" in program_description,
    "tree_has_repeat": "repeat $amplification" in program_tree,
    "tree_has_parallel_readout": "parallel" in program_tree,
}

show(program_description)
show(program_tree)
show(program_inspection_summary)

"""Notebook-style example: try, accept, and undo an analysis candidate."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import EXAMPLE_ROOT
from quantum_lab_demo.workflows.readout_frequency import (
    readout_frequency_analysis,
    readout_frequency_template,
)

# %%
lab = sc.open_project(EXAMPLE_ROOT).connect()

# %%
baseline = lab.prepare(readout_frequency_template(qubit="q0")).run(
    name="readout frequency baseline",
    tags=("notebook", "calibration", "baseline"),
)
analysis = baseline.analyze(readout_frequency_analysis(qubit="q0"))
saved_analysis = analysis.save()

# %%
candidate = analysis.candidate_config()
# Running with a durable candidate is optional. It records the producing
# analysis and proposal without changing the default configuration.
follow_up = lab.prepare(readout_frequency_template(qubit="q0"), config=candidate).run(
    name="readout frequency follow-up",
    tags=("notebook", "calibration", "candidate"),
)

# %%
# Accepting the same durable candidate records the human decision and makes its
# resolved snapshot the default. It does not depend on the optional run above.
accepted = lab.config.accept(
    candidate,
    note="accept the readout fit for ordinary runs",
)
default_run = lab.prepare(readout_frequency_template(qubit="q0")).run(
    name="readout frequency with accepted default",
    tags=("notebook", "calibration", "default"),
)
restored = lab.config.undo(
    note="restore the previous default after the walkthrough",
)

# %%
proposal = analysis.parameter_proposals[0]
candidate_source = follow_up.manifest.config_source
default_source = default_run.manifest.config_source
summary = {
    "baseline": baseline.id,
    "parameter_change": proposal.id,
    "saved_analysis": saved_analysis.record.id,
    "candidate_proposals": candidate.proposal_ids,
    "follow_up": follow_up.id,
    "candidate_source": (
        candidate_source.kind if candidate_source is not None else None
    ),
    "default_run_source": (default_source.kind if default_source is not None else None),
    "accepted_as_default": (
        default_source is not None
        and default_source.content_hash == accepted.entry.content_hash
    ),
    "default_restored": (
        restored.active_state.active_entry_content_hash
        == accepted.activation.previous_entry_content_hash
    ),
}
print(summary)

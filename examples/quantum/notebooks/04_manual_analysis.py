"""Notebook-style example: save manual analysis from notebook data."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.experiments import READOUT_TEMPLATE

# %%
workspace = notebook_workspace("04-manual-analysis")
lab = quantum_lab(workspace=workspace)

# %%
baseline = (
    lab.prepare(READOUT_TEMPLATE)
    .input("qubit", "q0")
    .run(
        name="readout frequency baseline",
        tags=("notebook", "calibration", "baseline"),
    )
)
raw = baseline.data().measurements()

# %%
rows = [
    {
        "point": record.point_index,
        "observables": sorted(record.observables),
    }
    for record in raw.dataset.records
]

analysis = (
    baseline.analysis("manual notebook review")
    .table(rows, title="raw measurement index")
    .input("raw-measurements", expected_kind="measurement_dataset")
    .propose(
        "readout_frequency",
        sc.update_parameter_rows(
            "qubits",
            key={"qubit": "q0"},
            values={"readout_frequency": sc.Quantity(5.953, "GHz")},
        ),
        reason="lowest S21 point in the readout scan",
        confidence=0.8,
    )
)
saved_analysis = analysis.save()

# %%
candidate = analysis.candidate_config()
follow_up = (
    lab.prepare(READOUT_TEMPLATE, config=candidate)
    .input("qubit", "q0")
    .run(
        name="readout frequency follow-up",
        tags=("notebook", "calibration", "candidate"),
    )
)

# %%
proposal = analysis.parameter_proposals[0]
delta = proposal.deltas[0]
summary = {
    "baseline": baseline.id,
    "follow_up": follow_up.id,
    "measurements": len(raw.dataset.records),
    "saved_analysis": saved_analysis.record.id,
    "candidate_proposals": candidate.proposal_ids,
    "parameter_change": f"{delta.parameter_id} = {delta.after}",
}
print(summary)

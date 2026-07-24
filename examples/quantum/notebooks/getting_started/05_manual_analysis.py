"""Notebook-style example: save manual analysis from notebook data."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import EXAMPLE_ROOT
from quantum_lab_demo.workflows.readout_frequency import readout_frequency_template

# %%
lab = sc.open_project(EXAMPLE_ROOT).connect()

# %%
baseline = lab.prepare(readout_frequency_template(qubit="q0")).run(
    name="readout frequency baseline",
    tags=("notebook", "calibration", "baseline"),
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
durable_proposals = lab.config.proposals(baseline)

# %%
candidate = analysis.candidate_config()

# %%
proposal = analysis.parameter_proposals[0]
delta = proposal.deltas[0]
summary = {
    "baseline": baseline.id,
    "measurements": len(raw.dataset.records),
    "saved_analysis": saved_analysis.record.id,
    "durable_proposals": len(durable_proposals.items),
    "candidate_proposals": candidate.proposal_ids,
    "parameter_change": f"{delta.parameter_id} = {delta.after}",
}
print(summary)

"""Notebook-style example: save manual analysis from notebook data."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import notebook_workspace, readout_frequency_lab
from quantum_lab_demo.readout import frequency_calibration

# %%
workspace = notebook_workspace("04-manual-analysis")
lab = readout_frequency_lab(workspace=workspace)
experiment = lab.experiment(
    "readout frequency",
    source=frequency_calibration(qubit="q0"),
)

# %%
baseline = lab.run(experiment)
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
        sc.set_param("readout_frequency", sc.Quantity(5.953, "GHz")),
        reason="lowest S21 point in the readout sweep",
        confidence=0.8,
    )
)
saved_analysis = analysis.save()

# %%
candidate = analysis.candidate_config()
follow_up = lab.run(experiment, config=candidate)

# %%
change = analysis.parameter_changes[0]
patch = change.patches[0]
summary = {
    "baseline": baseline.id,
    "follow_up": follow_up.id,
    "measurements": len(raw.dataset.records),
    "saved_analysis": saved_analysis.artifact.id,
    "candidate": candidate.analysis_key,
    "parameter_change": f"{patch.parameter_id} = {patch.value}",
}
print(summary)

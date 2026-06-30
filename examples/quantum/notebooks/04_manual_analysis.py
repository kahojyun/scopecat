"""Notebook-style example: save manual analysis from notebook data."""

from __future__ import annotations

# %%
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
    .note("Inspected the readout sweep in a notebook.")
    .table(rows, title="raw measurement index")
    .artifact_ref("raw-measurements", expected_kind="measurement_dataset")
    .guess(
        "readout_frequency",
        5.953,
        unit="GHz",
        reason="manual notebook pick from the lowest S21 point",
        confidence=0.8,
    )
)
saved_analysis = analysis.save()

# %%
candidate = analysis.candidate_config(reason="manual notebook review")
review = lab.review(candidate, note="approved from notebook example")
follow_up = lab.run(experiment, config=review)

# %%
guess = analysis.parameter_guesses[0]
summary = {
    "baseline": baseline.id,
    "follow_up": follow_up.id,
    "measurements": len(raw.dataset.records),
    "saved_analysis": saved_analysis.artifact.id,
    "candidate": review.candidate_config_artifact.id,
    "guess": f"{guess.parameter_id} = {guess.value} {guess.unit}",
}
print(summary)

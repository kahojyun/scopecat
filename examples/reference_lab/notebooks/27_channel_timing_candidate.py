"""Review a channel timing update against a real two-qubit run."""

from __future__ import annotations

# %%
import scopecat as sc

from reference_lab.configuration import EXAMPLE_ROOT
from reference_lab.notebook import show
from reference_lab.parameters import CHANNEL_DELAY, Q1_CHANNEL_CALIBRATION
from reference_lab.workflows.ramsey_experiments import parallel_two_qubit_ramsey

# %%
with sc.open_project(EXAMPLE_ROOT).connect(operator="gallery") as lab:
    source_run = lab.run(
        parallel_two_qubit_ramsey(),
        name="Channel timing source",
        tags=("gallery", "channel-calibration"),
    )
    analysis = (
        source_run.analysis("q1 channel timing review")
        .result()
        .propose(
            "q1-channel-delay",
            Q1_CHANNEL_CALIBRATION.update(CHANNEL_DELAY.value(1.0)),
            reason="align q1 acquisition with the shared readout window",
        )
    )
    published = analysis.save()
    candidate = published.candidate_config()
    candidate_run = lab.run(
        parallel_two_qubit_ramsey(),
        config=candidate,
        name="Channel timing candidate check",
        tags=("gallery", "channel-calibration", "candidate"),
    )
    source = candidate_run.manifest.config_source
    candidate_status = candidate_run.manifest.status

channel_candidate_summary = {
    "analysis": published.id,
    "proposal_id": candidate.proposal_id,
    "candidate_status": candidate_status,
    "candidate_provenance": (
        source is not None
        and source.kind == "analysis_candidate"
        and source.proposal_id == candidate.proposal_id
    ),
}
show(channel_candidate_summary)

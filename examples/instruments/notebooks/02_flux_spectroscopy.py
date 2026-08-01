"""Run and analyze vendor-neutral resonator flux spectroscopy."""

from __future__ import annotations

# %%
from pathlib import Path

import scopecat as sc

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# %%
with sc.open_project(PROJECT_ROOT).connect(operator="notebook-demo") as lab:
    # Connecting loads this project's ``src`` tree before workflow imports.
    from instrument_demo.workflows.flux_spectroscopy import (
        flux_spectroscopy_template,
    )
    from instrument_demo.workflows.flux_spectroscopy_analysis import (
        flux_spectroscopy_analysis,
    )

    invocation = flux_spectroscopy_template()
    preview = lab.preview(invocation)
    run = lab.run(
        invocation,
        name="Virtual resonator flux spectroscopy",
        tags=("spectroscopy", "virtual-instruments"),
    )

    analysis = run.analyze(flux_spectroscopy_analysis())
    saved_analysis = analysis.save()
    candidate = analysis.candidate_config()
    candidate_snapshot = lab.resolve_config(candidate)
    [proposal] = analysis.parameter_proposals

    summary = {
        "run_id": run.manifest.run_id,
        "status": run.manifest.status,
        "point_count": preview.point_count,
        "measurement_records": len(run.data().measurements().dataset.records),
        "analysis_id": saved_analysis.record.id,
        "proposal_id": proposal.id,
        "candidate_config_id": candidate_snapshot.id,
    }

print(summary)

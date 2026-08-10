"""Run, rediscover, and resume a measurement-dependent tune-up sequence."""

from __future__ import annotations

# %%
import scopecat as sc
from scopecat.api.lab import SequenceRun

from reference_lab.configuration import EXAMPLE_ROOT
from reference_lab.notebook import show
from reference_lab.workflows.flux_spectroscopy import flux_spectroscopy
from reference_lab.workflows.flux_spectroscopy_analysis import (
    fit_flux_spectroscopy,
)

TARGET_RESONANCE = sc.Quantity(5.055, "GHz")


def flux_point(bias: sc.Quantity):
    invocation = flux_spectroscopy()
    return invocation.points(({invocation.output.dc_bias: bias},))


def choose_next(sequence_run: SequenceRun):
    """Advance toward zero bias until the measured resonance reaches target."""

    [fit] = fit_flux_spectroscopy(sequence_run.measurements())
    resonance_hz = float(fit.resonance_frequency.to("Hz").value)
    target_hz = float(TARGET_RESONANCE.to("Hz").value)
    if resonance_hz >= target_hz:
        return None
    bias_v = float(fit.dc_bias.to("V").value)
    next_bias_v = bias_v + 0.1 if bias_v < 0 else bias_v - 0.1
    return flux_point(sc.Quantity(next_bias_v, "V"))


# %%
with sc.open_project(EXAMPLE_ROOT).connect(operator="gallery") as lab:
    limited = lab.run_sequence(
        flux_point(sc.Quantity(-0.2, "V")),
        next_run=choose_next,
        max_runs=4,
        max_new_runs=2,
        name="Adaptive resonator tune-up",
        tags=("gallery", "adaptive"),
    )
    rediscovered = lab.get_run_sequence(limited.sequence_id)
    resumed = lab.resume_sequence(
        rediscovered.sequence_id,
        next_run=choose_next,
        max_new_runs=2,
    )

adaptive_summary = {
    "sequence_id": resumed.sequence_id,
    "initial_runs": len(limited.sequence_runs),
    "initial_status": limited.status,
    "rediscovered_runs": len(rediscovered.sequence_runs),
    "completed_runs": len(resumed.sequence_runs),
    "final_status": resumed.status,
}
show(adaptive_summary)

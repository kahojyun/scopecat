"""Run, rediscover, and resume a measurement-dependent staged tune-up."""

from __future__ import annotations

# %%
import scopecat as sc
from scopecat.api.lab import ExperimentStage

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


def choose_next(stage: ExperimentStage):
    """Advance toward zero bias until the measured resonance reaches target."""

    [fit] = fit_flux_spectroscopy(stage.run.measurements())
    resonance_hz = float(fit.resonance_frequency.to("Hz").value)
    target_hz = float(TARGET_RESONANCE.to("Hz").value)
    if resonance_hz >= target_hz:
        return None
    bias_v = float(fit.dc_bias.to("V").value)
    next_bias_v = bias_v + 0.1 if bias_v < 0 else bias_v - 0.1
    return flux_point(sc.Quantity(next_bias_v, "V"))


# %%
with sc.open_project(EXAMPLE_ROOT).connect(operator="gallery") as lab:
    limited = lab.run_staged(
        flux_point(sc.Quantity(-0.2, "V")),
        next_stage=choose_next,
        max_stages=2,
        name="Adaptive resonator tune-up",
        tags=("gallery", "adaptive"),
    )
    rediscovered = lab.get_staged_experiment(limited.sequence_id)
    resumed = lab.resume_staged(
        rediscovered.sequence_id,
        next_stage=choose_next,
        max_stages=2,
    )

adaptive_summary = {
    "sequence_id": resumed.sequence_id,
    "initial_stages": len(limited.stages),
    "stopped_by_limit": limited.stopped_by_limit,
    "rediscovered_stages": len(rediscovered.stages),
    "completed_stages": len(resumed.stages),
    "resumed_to_completion": resumed.stopped_by_limit is False,
}
show(adaptive_summary)

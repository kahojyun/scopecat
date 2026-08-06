"""Four-qubit DC bias orchestration across two physical sources."""

from __future__ import annotations

from dataclasses import dataclass

import scopecat as sc
from scopecat.kernel.entity import EntityRef
from scopecat_instruments import DCSourceGroupTarget, dc_source, temperature_readout

from reference_lab.workflows.flux_spectroscopy import CRYOSTAT, TEMPERATURE_RESOURCE

Q0 = EntityRef(id="q0", kind="logical_qubit")
Q1 = EntityRef(id="q1", kind="logical_qubit")
Q2 = EntityRef(id="q2", kind="logical_qubit")
Q3 = EntityRef(id="q3", kind="logical_qubit")
QUBIT_SELECTION = sc.each(Q0, Q1, Q2, Q3)
BIAS_LEVELS = sc.PerEntity(
    (
        (Q0, sc.Quantity(-0.08, "V")),
        (Q1, sc.Quantity(-0.02, "V")),
        (Q2, sc.Quantity(0.04, "V")),
        (Q3, sc.Quantity(0.10, "V")),
    )
)


@dataclass(frozen=True, slots=True)
class MultiChannelBiasDataset:
    temperature: sc.RecordRef[float]


@sc.experiment(id="reference_lab.multichannel_dc_bias")
def multichannel_dc_bias(
    experiment: sc.ExperimentContext,
) -> MultiChannelBiasDataset:
    """Set four independent lines on two devices and always return them to off."""

    biases = dc_source(experiment, "flux-bias", for_=QUBIT_SELECTION)
    biases.ensure(
        current_protection=sc.Quantity(100.0, "uA"),
        output_enabled=False,
    )
    biases.source_voltage(range=sc.Quantity(1.0, "V"), level=BIAS_LEVELS)
    biases.ensure(output_enabled=True)
    thermometer = temperature_readout(
        experiment,
        TEMPERATURE_RESOURCE,
        for_=sc.one(CRYOSTAT),
    )
    sample = thermometer.sample()
    experiment.on_success(biases, DCSourceGroupTarget(output_enabled=False))
    return MultiChannelBiasDataset(
        temperature=experiment.record(sample.temperature),
    )


MULTICHANNEL_DC_BIAS = multichannel_dc_bias()


__all__ = [
    "BIAS_LEVELS",
    "MULTICHANNEL_DC_BIAS",
    "MultiChannelBiasDataset",
    "multichannel_dc_bias",
]

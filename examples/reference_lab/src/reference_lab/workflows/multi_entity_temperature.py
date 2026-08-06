"""Entity-aligned group acquisition from two routed thermometers."""

from __future__ import annotations

from dataclasses import dataclass

import scopecat as sc
from scopecat.kernel.entity import EntityRef
from scopecat_instruments import temperature_readout

Q0 = EntityRef(id="q0", kind="logical_qubit")
Q1 = EntityRef(id="q1", kind="logical_qubit")


@dataclass(frozen=True, slots=True)
class MultiEntityTemperatureDataset:
    q0_temperature: sc.RecordRef[float]
    q1_temperature: sc.RecordRef[float]


@sc.experiment(id="reference_lab.multi_entity_temperature")
def multi_entity_temperature(
    experiment: sc.ExperimentContext,
) -> MultiEntityTemperatureDataset:
    """Route one typed group acquisition to q0 and q1 sensors."""

    thermometers = temperature_readout(
        experiment,
        "thermometers",
        for_=sc.each(Q0, Q1),
    )
    samples = thermometers.sample()
    return MultiEntityTemperatureDataset(
        q0_temperature=experiment.record(samples[Q0].temperature),
        q1_temperature=experiment.record(samples[Q1].temperature),
    )


__all__ = ["MultiEntityTemperatureDataset", "multi_entity_temperature"]

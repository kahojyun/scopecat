"""Vendor-neutral resonator spectroscopy over a DC flux-bias scan."""

from __future__ import annotations

import scopecat as sc
from scopecat_instruments import (
    DCSourceState,
    DCSourceVoltage,
    NetworkSweepState,
    dc_source,
    network_sweep,
    temperature_readout,
)

FLUX_SPECTROSCOPY_TEMPLATE_ID = "instrument_demo.flux_spectroscopy"
FLUX_SPECTROSCOPY_EXPERIMENT_ID = "resonator-flux-spectroscopy"

FLUX_SOURCE_RESOURCE = "flux-source"
TEMPERATURE_RESOURCE = "mixing-chamber"
VNA_RESOURCE = "readout-vna"

TRACE_POINTS = 751
BIAS_POINTS = 11
BIAS_CENTER = sc.Quantity(0.0, "V")
BIAS_SPAN = sc.Quantity(0.5, "V")
SWEEP_START = sc.Quantity(4.93, "GHz")
SWEEP_STOP = sc.Quantity(5.08, "GHz")

DC_BIAS = sc.coordinate(
    "dc_bias",
    sc.ScalarType(sc.QuantityType(unit="V")),
)


@sc.template(
    id=FLUX_SPECTROSCOPY_TEMPLATE_ID,
    kind=FLUX_SPECTROSCOPY_EXPERIMENT_ID,
)
def flux_spectroscopy_template(experiment: sc.ExperimentContext) -> None:
    """Scan DC bias and persist one VNA trace plus temperature per point."""

    experiment.scan(
        sc.axis(
            DC_BIAS,
            center=BIAS_CENTER,
            span=BIAS_SPAN,
            points=BIAS_POINTS,
        )
    )
    flux_source = dc_source(experiment, FLUX_SOURCE_RESOURCE)
    temperature = temperature_readout(experiment, TEMPERATURE_RESOURCE)
    readout = network_sweep(experiment, VNA_RESOURCE)

    flux_source.ensure(
        DCSourceVoltage(
            range=sc.Quantity(1.0, "V"),
            level=DC_BIAS,
            current_protection=sc.Quantity(100.0, "uA"),
            output_enabled=True,
        )
    )
    readout.ensure(
        NetworkSweepState(
            start_frequency=SWEEP_START,
            stop_frequency=SWEEP_STOP,
            points=TRACE_POINTS,
            if_bandwidth=sc.Quantity(1.0, "kHz"),
            source_power=sc.Quantity(-35.0, "dBm"),
            s_parameter="S21",
        )
    )
    trace = readout.sweep()
    sample = temperature.sample()
    flux_source.ensure(DCSourceState(output_enabled=False))

    experiment.record_coordinate(trace.frequency)
    experiment.record(
        trace.s_parameter,
        sample.temperature,
    )


__all__ = [
    "BIAS_CENTER",
    "BIAS_POINTS",
    "BIAS_SPAN",
    "DC_BIAS",
    "FLUX_SPECTROSCOPY_EXPERIMENT_ID",
    "FLUX_SPECTROSCOPY_TEMPLATE_ID",
    "TRACE_POINTS",
    "flux_spectroscopy_template",
]

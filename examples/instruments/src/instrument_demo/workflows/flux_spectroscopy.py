"""Vendor-neutral resonator spectroscopy over a DC flux-bias scan."""

from __future__ import annotations

import scopecat as sc
from scopecat_instruments.members import (
    DC_SOURCE,
    NETWORK_SWEEP,
    NETWORK_SWEEP_FREQUENCY_RESULT,
    NETWORK_SWEEP_S_PARAMETER_RESULT,
    TEMPERATURE_READOUT,
    TEMPERATURE_READOUT_TEMPERATURE_RESULT,
)
from scopecat_instruments.states import (
    DCSourceState,
    DCSourceVoltage,
    NetworkSweepState,
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
_FREQUENCY_AXIS = sc.product_axis(
    "frequency",
    size=TRACE_POINTS,
    kind="frequency",
    unit="Hz",
    shared_as="frequency_sample",
)


@sc.module(id="instrument_demo.flux_spectroscopy.capture")
def _flux_spectroscopy_module():
    return (
        sc.module_body()
        .resource(FLUX_SOURCE_RESOURCE, requires=(DC_SOURCE,))
        .resource(
            TEMPERATURE_RESOURCE,
            requires=(TEMPERATURE_READOUT,),
        )
        .resource(VNA_RESOURCE, requires=(NETWORK_SWEEP,))
        .ensure(
            FLUX_SOURCE_RESOURCE,
            DCSourceVoltage(
                range=sc.Quantity(1.0, "V"),
                level=DC_BIAS,
                current_protection=sc.Quantity(100.0, "uA"),
                output_enabled=True,
            ),
        )
        .ensure(
            VNA_RESOURCE,
            NetworkSweepState(
                start_frequency=SWEEP_START,
                stop_frequency=SWEEP_STOP,
                points=TRACE_POINTS,
                if_bandwidth=sc.Quantity(1.0, "kHz"),
                source_power=sc.Quantity(-35.0, "dBm"),
                s_parameter="S21",
            ),
        )
        .product(
            "frequency",
            dtype="float64",
            unit="Hz",
            axes=(_FREQUENCY_AXIS,),
        )
        .product(
            "s_parameter",
            dtype="complex128",
            unit="ratio",
            axes=(_FREQUENCY_AXIS,),
        )
        .product("temperature", dtype="float64", unit="K")
        .acquire(
            "read-network-trace",
            resource=VNA_RESOURCE,
            results={
                NETWORK_SWEEP_FREQUENCY_RESULT: "frequency",
                NETWORK_SWEEP_S_PARAMETER_RESULT: "s_parameter",
            },
        )
        .acquire(
            "read-temperature",
            resource=TEMPERATURE_RESOURCE,
            results={TEMPERATURE_READOUT_TEMPERATURE_RESULT: "temperature"},
        )
        .ensure(
            FLUX_SOURCE_RESOURCE,
            DCSourceState(output_enabled=False),
        )
    )


@sc.template(
    id=FLUX_SPECTROSCOPY_TEMPLATE_ID,
    kind=FLUX_SPECTROSCOPY_EXPERIMENT_ID,
)
def flux_spectroscopy_template() -> sc.ExperimentBody:
    """Scan DC bias and persist one VNA trace plus temperature per point."""

    capture = _flux_spectroscopy_module()
    return (
        sc.experiment(capture)
        .scan(
            sc.axis(
                DC_BIAS,
                center=BIAS_CENTER,
                span=BIAS_SPAN,
                points=BIAS_POINTS,
            )
        )
        .record_coordinate(capture.products.frequency)
        .record_product(
            capture.products.s_parameter,
            capture.products.temperature,
        )
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

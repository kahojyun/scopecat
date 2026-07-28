"""Vendor-neutral resonator spectroscopy over a DC flux-bias scan."""

from __future__ import annotations

import scopecat as sc
from scopecat_instruments.interfaces import (
    DC_SOURCE,
    NETWORK_SWEEP,
    TEMPERATURE_READOUT,
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
)


def _flux_spectroscopy_module() -> sc.ExperimentModule[...]:
    return (
        sc.module_body(id="instrument_demo.flux_spectroscopy.capture")
        .resource(FLUX_SOURCE_RESOURCE, requires=(DC_SOURCE,))
        .resource(TEMPERATURE_RESOURCE, requires=(TEMPERATURE_READOUT,))
        .resource(VNA_RESOURCE, requires=(NETWORK_SWEEP,))
        .bind_property(
            FLUX_SOURCE_RESOURCE,
            interface=DC_SOURCE,
            property="source_mode",
            value="voltage",
        )
        .bind_property(
            FLUX_SOURCE_RESOURCE,
            interface=DC_SOURCE,
            property="voltage_range",
            value=sc.Quantity(1.0, "V"),
        )
        .bind_property(
            FLUX_SOURCE_RESOURCE,
            interface=DC_SOURCE,
            property="current_protection",
            value=sc.Quantity(100.0, "uA"),
        )
        .bind_property(
            FLUX_SOURCE_RESOURCE,
            interface=DC_SOURCE,
            property="voltage_level",
            value=DC_BIAS,
        )
        .bind_property(
            FLUX_SOURCE_RESOURCE,
            interface=DC_SOURCE,
            property="output_enabled",
            value=True,
        )
        .bind_property(
            VNA_RESOURCE,
            interface=NETWORK_SWEEP,
            property="start_frequency",
            value=SWEEP_START,
        )
        .bind_property(
            VNA_RESOURCE,
            interface=NETWORK_SWEEP,
            property="stop_frequency",
            value=SWEEP_STOP,
        )
        .bind_property(
            VNA_RESOURCE,
            interface=NETWORK_SWEEP,
            property="points",
            value=TRACE_POINTS,
        )
        .bind_property(
            VNA_RESOURCE,
            interface=NETWORK_SWEEP,
            property="if_bandwidth",
            value=sc.Quantity(1.0, "kHz"),
        )
        .bind_property(
            VNA_RESOURCE,
            interface=NETWORK_SWEEP,
            property="source_power",
            value=sc.Quantity(-35.0, "dBm"),
        )
        .bind_property(
            VNA_RESOURCE,
            interface=NETWORK_SWEEP,
            property="s_parameter",
            value="S21",
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
            "frequency",
            "s_parameter",
            resource=VNA_RESOURCE,
            interface=NETWORK_SWEEP,
            acquisition="sweep",
        )
        .acquire(
            "read-temperature",
            "temperature",
            resource=TEMPERATURE_RESOURCE,
            interface=TEMPERATURE_READOUT,
            acquisition="sample",
        )
        .bind_property(
            FLUX_SOURCE_RESOURCE,
            interface=DC_SOURCE,
            property="output_enabled",
            value=False,
        )
        .build()
    )


@sc.template(
    id=FLUX_SPECTROSCOPY_TEMPLATE_ID,
    kind=FLUX_SPECTROSCOPY_EXPERIMENT_ID,
)
def flux_spectroscopy_template() -> sc.ExperimentBody:
    """Scan DC bias and persist one VNA trace plus temperature per point."""

    capture = _flux_spectroscopy_module()()
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
        .record_product(
            capture.products.frequency,
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
    "NETWORK_SWEEP",
    "TRACE_POINTS",
    "flux_spectroscopy_template",
]

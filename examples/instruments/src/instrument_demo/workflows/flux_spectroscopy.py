"""Vendor-neutral resonator spectroscopy over a DC flux-bias scan."""

from __future__ import annotations

import scopecat as sc
from scopecat_instruments.members import (
    DC_SOURCE,
    DC_SOURCE_CURRENT_PROTECTION,
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE_LEVEL,
    DC_SOURCE_VOLTAGE_RANGE,
    NETWORK_SWEEP,
    NETWORK_SWEEP_FREQUENCY_RESULT,
    NETWORK_SWEEP_IF_BANDWIDTH,
    NETWORK_SWEEP_POINTS,
    NETWORK_SWEEP_S_PARAMETER,
    NETWORK_SWEEP_S_PARAMETER_RESULT,
    NETWORK_SWEEP_SOURCE_POWER,
    NETWORK_SWEEP_START_FREQUENCY,
    NETWORK_SWEEP_STOP_FREQUENCY,
    TEMPERATURE_READOUT,
    TEMPERATURE_READOUT_TEMPERATURE_RESULT,
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
        .resource(
            TEMPERATURE_RESOURCE,
            requires=(TEMPERATURE_READOUT,),
        )
        .resource(VNA_RESOURCE, requires=(NETWORK_SWEEP,))
        .bind_property(
            FLUX_SOURCE_RESOURCE,
            DC_SOURCE_MODE,
            value="voltage",
        )
        .bind_property(
            FLUX_SOURCE_RESOURCE,
            DC_SOURCE_VOLTAGE_RANGE,
            value=sc.Quantity(1.0, "V"),
        )
        .bind_property(
            FLUX_SOURCE_RESOURCE,
            DC_SOURCE_CURRENT_PROTECTION,
            value=sc.Quantity(100.0, "uA"),
        )
        .bind_property(
            FLUX_SOURCE_RESOURCE,
            DC_SOURCE_VOLTAGE_LEVEL,
            value=DC_BIAS,
        )
        .bind_property(
            FLUX_SOURCE_RESOURCE,
            DC_SOURCE_OUTPUT_ENABLED,
            value=True,
        )
        .bind_property(
            VNA_RESOURCE,
            NETWORK_SWEEP_START_FREQUENCY,
            value=SWEEP_START,
        )
        .bind_property(
            VNA_RESOURCE,
            NETWORK_SWEEP_STOP_FREQUENCY,
            value=SWEEP_STOP,
        )
        .bind_property(
            VNA_RESOURCE,
            NETWORK_SWEEP_POINTS,
            value=TRACE_POINTS,
        )
        .bind_property(
            VNA_RESOURCE,
            NETWORK_SWEEP_IF_BANDWIDTH,
            value=sc.Quantity(1.0, "kHz"),
        )
        .bind_property(
            VNA_RESOURCE,
            NETWORK_SWEEP_SOURCE_POWER,
            value=sc.Quantity(-35.0, "dBm"),
        )
        .bind_property(
            VNA_RESOURCE,
            NETWORK_SWEEP_S_PARAMETER,
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
        .bind_property(
            FLUX_SOURCE_RESOURCE,
            DC_SOURCE_OUTPUT_ENABLED,
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
    "TRACE_POINTS",
    "flux_spectroscopy_template",
]

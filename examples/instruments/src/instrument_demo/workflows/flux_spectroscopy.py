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
    NETWORK_SWEEP_ACQUISITION,
    NETWORK_SWEEP_IF_BANDWIDTH,
    NETWORK_SWEEP_POINTS,
    NETWORK_SWEEP_S_PARAMETER,
    NETWORK_SWEEP_SOURCE_POWER,
    NETWORK_SWEEP_START_FREQUENCY,
    NETWORK_SWEEP_STOP_FREQUENCY,
    TEMPERATURE_READOUT,
    TEMPERATURE_READOUT_SAMPLE,
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
        .resource(FLUX_SOURCE_RESOURCE, requires=(DC_SOURCE.interface_id,))
        .resource(
            TEMPERATURE_RESOURCE,
            requires=(TEMPERATURE_READOUT.interface_id,),
        )
        .resource(VNA_RESOURCE, requires=(NETWORK_SWEEP.interface_id,))
        .bind_property(
            FLUX_SOURCE_RESOURCE,
            interface=DC_SOURCE_MODE.interface_id,
            property=DC_SOURCE_MODE.property_id,
            value="voltage",
        )
        .bind_property(
            FLUX_SOURCE_RESOURCE,
            interface=DC_SOURCE_VOLTAGE_RANGE.interface_id,
            property=DC_SOURCE_VOLTAGE_RANGE.property_id,
            value=sc.Quantity(1.0, "V"),
        )
        .bind_property(
            FLUX_SOURCE_RESOURCE,
            interface=DC_SOURCE_CURRENT_PROTECTION.interface_id,
            property=DC_SOURCE_CURRENT_PROTECTION.property_id,
            value=sc.Quantity(100.0, "uA"),
        )
        .bind_property(
            FLUX_SOURCE_RESOURCE,
            interface=DC_SOURCE_VOLTAGE_LEVEL.interface_id,
            property=DC_SOURCE_VOLTAGE_LEVEL.property_id,
            value=DC_BIAS,
        )
        .bind_property(
            FLUX_SOURCE_RESOURCE,
            interface=DC_SOURCE_OUTPUT_ENABLED.interface_id,
            property=DC_SOURCE_OUTPUT_ENABLED.property_id,
            value=True,
        )
        .bind_property(
            VNA_RESOURCE,
            interface=NETWORK_SWEEP_START_FREQUENCY.interface_id,
            property=NETWORK_SWEEP_START_FREQUENCY.property_id,
            value=SWEEP_START,
        )
        .bind_property(
            VNA_RESOURCE,
            interface=NETWORK_SWEEP_STOP_FREQUENCY.interface_id,
            property=NETWORK_SWEEP_STOP_FREQUENCY.property_id,
            value=SWEEP_STOP,
        )
        .bind_property(
            VNA_RESOURCE,
            interface=NETWORK_SWEEP_POINTS.interface_id,
            property=NETWORK_SWEEP_POINTS.property_id,
            value=TRACE_POINTS,
        )
        .bind_property(
            VNA_RESOURCE,
            interface=NETWORK_SWEEP_IF_BANDWIDTH.interface_id,
            property=NETWORK_SWEEP_IF_BANDWIDTH.property_id,
            value=sc.Quantity(1.0, "kHz"),
        )
        .bind_property(
            VNA_RESOURCE,
            interface=NETWORK_SWEEP_SOURCE_POWER.interface_id,
            property=NETWORK_SWEEP_SOURCE_POWER.property_id,
            value=sc.Quantity(-35.0, "dBm"),
        )
        .bind_property(
            VNA_RESOURCE,
            interface=NETWORK_SWEEP_S_PARAMETER.interface_id,
            property=NETWORK_SWEEP_S_PARAMETER.property_id,
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
            interface=NETWORK_SWEEP_ACQUISITION.interface_id,
            acquisition=NETWORK_SWEEP_ACQUISITION.acquisition_id,
        )
        .acquire(
            "read-temperature",
            "temperature",
            resource=TEMPERATURE_RESOURCE,
            interface=TEMPERATURE_READOUT_SAMPLE.interface_id,
            acquisition=TEMPERATURE_READOUT_SAMPLE.acquisition_id,
        )
        .bind_property(
            FLUX_SOURCE_RESOURCE,
            interface=DC_SOURCE_OUTPUT_ENABLED.interface_id,
            property=DC_SOURCE_OUTPUT_ENABLED.property_id,
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

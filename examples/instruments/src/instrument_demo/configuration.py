"""Source-controlled bootstrap configuration for the virtual instrument lab."""

from __future__ import annotations

from scopecat.authoring import QuantityType, ScalarType
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.records.config import (
    ConfigProfileSnapshot,
    InstrumentRegistry,
    InstrumentSpec,
    RoutingEndpointBinding,
    RoutingGraph,
    SystemSpec,
    Topology,
    VirtualInstrumentConnection,
    snapshot_config_profile,
)
from scopecat.records.instrument import InstrumentPropertyState
from scopecat.records.parameter import (
    ParameterCatalog,
    ParameterDefinition,
    ParameterSnapshot,
    ScalarParameterValue,
)
from scopecat.sdk.instruments import PropertyRef
from scopecat_instruments.driver_ids import (
    VIRTUAL_DC_SOURCE,
    VIRTUAL_RF_SOURCE,
    VIRTUAL_TEMPERATURE_MONITOR,
    VIRTUAL_VNA,
)
from scopecat_instruments.members import (
    DC_MONITOR,
    DC_SOURCE,
    DC_SOURCE_CURRENT_PROTECTION,
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE_LEVEL,
    DC_SOURCE_VOLTAGE_PROTECTION,
    DC_SOURCE_VOLTAGE_RANGE,
    NETWORK_SWEEP,
    RF_OUTPUT,
    TEMPERATURE_READOUT,
)

RESONANCE_FREQUENCY_PARAMETER_ID = "readout_resonance_frequency"
RESONATOR_LINEWIDTH_PARAMETER_ID = "readout_resonator_linewidth"


def bootstrap_config() -> ConfigProfileSnapshot:
    """Declare four coupled devices without requiring external hardware."""

    return snapshot_config_profile(
        profile_id="virtual-instrument-lab",
        system=SystemSpec(
            id="virtual-instrument-system",
            primary_entity_id="sample",
            topology=Topology(
                entities=[EntityRef(id="sample", kind="sample")],
            ),
            instrument_registry=InstrumentRegistry(
                instruments=[
                    _virtual_instrument(
                        "pump-source",
                        driver_id=VIRTUAL_RF_SOURCE,
                    ),
                    _virtual_instrument(
                        "flux-source",
                        driver_id=VIRTUAL_DC_SOURCE,
                    ),
                    _virtual_instrument(
                        "mixing-chamber",
                        driver_id=VIRTUAL_TEMPERATURE_MONITOR,
                    ),
                    _virtual_instrument(
                        "readout-vna",
                        driver_id=VIRTUAL_VNA,
                    ),
                ]
            ),
            routing=RoutingGraph(
                bindings=[
                    RoutingEndpointBinding(
                        instrument_id="pump-source",
                        interface_id=RF_OUTPUT.interface_id,
                    ),
                    RoutingEndpointBinding(
                        instrument_id="flux-source",
                        interface_id=DC_SOURCE.interface_id,
                    ),
                    RoutingEndpointBinding(
                        instrument_id="flux-source",
                        interface_id=DC_MONITOR.interface_id,
                    ),
                    RoutingEndpointBinding(
                        instrument_id="mixing-chamber",
                        interface_id=TEMPERATURE_READOUT.interface_id,
                    ),
                    RoutingEndpointBinding(
                        instrument_id="readout-vna",
                        interface_id=NETWORK_SWEEP.interface_id,
                    ),
                ]
            ),
            domain_target=None,
            parameter_catalog=ParameterCatalog(
                id="virtual-instrument-parameters",
                definitions=[
                    ParameterDefinition(
                        id=RESONANCE_FREQUENCY_PARAMETER_ID,
                        value_type=ScalarType(QuantityType(unit="Hz")),
                        description=(
                            "Reviewed readout-resonator frequency at the selected "
                            "flux sweet spot."
                        ),
                    ),
                    ParameterDefinition(
                        id=RESONATOR_LINEWIDTH_PARAMETER_ID,
                        value_type=ScalarType(QuantityType(unit="Hz")),
                        description=(
                            "Reviewed loaded linewidth of the readout resonator."
                        ),
                    ),
                ],
            ),
        ),
        parameter_snapshot=ParameterSnapshot(
            id="virtual-instrument-values",
            values=[
                ScalarParameterValue(
                    id=RESONANCE_FREQUENCY_PARAMETER_ID,
                    value=Quantity(5.0e9, "Hz"),
                ),
                ScalarParameterValue(
                    id=RESONATOR_LINEWIDTH_PARAMETER_ID,
                    value=Quantity(2.0e6, "Hz"),
                ),
            ],
        ),
    )


def _virtual_instrument(
    instrument_id: str,
    *,
    driver_id: str,
) -> InstrumentSpec:
    default_state: list[InstrumentPropertyState]
    if driver_id == VIRTUAL_DC_SOURCE:
        default_state = [
            _property_state(DC_SOURCE_MODE, StateValue("voltage")),
            _property_state(
                DC_SOURCE_VOLTAGE_RANGE,
                StateValue(Quantity(1.0, "V")),
            ),
            _property_state(
                DC_SOURCE_VOLTAGE_LEVEL,
                StateValue(Quantity(0.0, "V")),
            ),
            _property_state(
                DC_SOURCE_VOLTAGE_PROTECTION,
                StateValue(Quantity(1.0, "V")),
            ),
            _property_state(
                DC_SOURCE_CURRENT_PROTECTION,
                StateValue(Quantity(0.01, "A")),
            ),
            _property_state(DC_SOURCE_OUTPUT_ENABLED, StateValue(False)),
        ]
    else:
        default_state = []
    return InstrumentSpec(
        id=instrument_id,
        driver_id=driver_id,
        connection=VirtualInstrumentConnection(),
        default_state=default_state,
        run_start="apply_default_state" if default_state else "preserve",
    )


def _property_state(
    target: PropertyRef,
    value: StateValue,
) -> InstrumentPropertyState:
    return InstrumentPropertyState(
        interface_id=target.interface_id,
        component_path=list(target.component_path),
        property_id=target.property_id,
        value=value,
    )


__all__ = [
    "RESONANCE_FREQUENCY_PARAMETER_ID",
    "RESONATOR_LINEWIDTH_PARAMETER_ID",
    "bootstrap_config",
]

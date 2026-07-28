"""Source-controlled bootstrap configuration for the virtual instrument lab."""

from __future__ import annotations

from scopecat.authoring import QuantityType, ScalarType
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.records.config import (
    ApplyDefaultsRunPreparation,
    ConfigProfileSnapshot,
    InstrumentRegistry,
    InstrumentSpec,
    PreserveRunPreparation,
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
from scopecat_instruments.driver_ids import (
    VIRTUAL_DC_SOURCE,
    VIRTUAL_RF_SOURCE,
    VIRTUAL_TEMPERATURE_MONITOR,
    VIRTUAL_VNA,
)
from scopecat_instruments.interfaces import (
    DC_MONITOR,
    DC_SOURCE,
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
                        interface_id=RF_OUTPUT,
                    ),
                    RoutingEndpointBinding(
                        instrument_id="flux-source",
                        interface_id=DC_SOURCE,
                    ),
                    RoutingEndpointBinding(
                        instrument_id="flux-source",
                        interface_id=DC_MONITOR,
                    ),
                    RoutingEndpointBinding(
                        instrument_id="mixing-chamber",
                        interface_id=TEMPERATURE_READOUT,
                    ),
                    RoutingEndpointBinding(
                        instrument_id="readout-vna",
                        interface_id=NETWORK_SWEEP,
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
    run_preparation: PreserveRunPreparation | ApplyDefaultsRunPreparation
    if driver_id == VIRTUAL_DC_SOURCE:
        run_preparation = ApplyDefaultsRunPreparation(
            properties=[
                InstrumentPropertyState(
                    interface_id=DC_SOURCE,
                    property_id="source_mode",
                    value=StateValue("voltage"),
                ),
                InstrumentPropertyState(
                    interface_id=DC_SOURCE,
                    property_id="voltage_range",
                    value=StateValue(Quantity(1.0, "V")),
                ),
                InstrumentPropertyState(
                    interface_id=DC_SOURCE,
                    property_id="voltage_level",
                    value=StateValue(Quantity(0.0, "V")),
                ),
                InstrumentPropertyState(
                    interface_id=DC_SOURCE,
                    property_id="voltage_protection",
                    value=StateValue(Quantity(1.0, "V")),
                ),
                InstrumentPropertyState(
                    interface_id=DC_SOURCE,
                    property_id="current_protection",
                    value=StateValue(Quantity(0.01, "A")),
                ),
                InstrumentPropertyState(
                    interface_id=DC_SOURCE,
                    property_id="output_enabled",
                    value=StateValue(False),
                ),
            ]
        )
    else:
        run_preparation = PreserveRunPreparation()
    return InstrumentSpec(
        id=instrument_id,
        driver_id=driver_id,
        connection=VirtualInstrumentConnection(),
        run_preparation=run_preparation,
    )


__all__ = [
    "RESONANCE_FREQUENCY_PARAMETER_ID",
    "RESONATOR_LINEWIDTH_PARAMETER_ID",
    "bootstrap_config",
]

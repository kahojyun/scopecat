"""Source-controlled bootstrap configuration for the virtual instrument lab."""

from __future__ import annotations

from scopecat.kernel.entity import EntityRef
from scopecat.records.config import (
    ConfigProfileSnapshot,
    InstrumentRegistry,
    InstrumentSpec,
    SystemSpec,
    Topology,
    VirtualInstrumentConnection,
    snapshot_config_profile,
)
from scopecat.records.parameter import (
    ParameterCatalog,
    ParameterSnapshot,
)
from scopecat_instruments import (
    VIRTUAL_DC_SOURCE,
    VIRTUAL_RF_SOURCE,
    VIRTUAL_TEMPERATURE_MONITOR,
    VIRTUAL_VNA,
)


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
                        kind="rf_source",
                        driver_id=VIRTUAL_RF_SOURCE,
                    ),
                    _virtual_instrument(
                        "flux-source",
                        kind="dc_source",
                        driver_id=VIRTUAL_DC_SOURCE,
                    ),
                    _virtual_instrument(
                        "mixing-chamber",
                        kind="temperature_monitor",
                        driver_id=VIRTUAL_TEMPERATURE_MONITOR,
                    ),
                    _virtual_instrument(
                        "readout-vna",
                        kind="vector_network_analyzer",
                        driver_id=VIRTUAL_VNA,
                    ),
                ]
            ),
            domain_target=None,
            parameter_catalog=ParameterCatalog(
                id="virtual-instrument-parameters",
                definitions=[],
            ),
        ),
        parameter_snapshot=ParameterSnapshot(
            id="virtual-instrument-values",
            values=[],
        ),
    )


def _virtual_instrument(
    instrument_id: str,
    *,
    kind: str,
    driver_id: str,
) -> InstrumentSpec:
    return InstrumentSpec(
        id=instrument_id,
        kind=kind,
        driver_id=driver_id,
        connection=VirtualInstrumentConnection(),
    )


__all__ = ["bootstrap_config"]

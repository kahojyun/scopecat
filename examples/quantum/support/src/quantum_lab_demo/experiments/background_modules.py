"""background-state modules."""

from __future__ import annotations

import scopecat as sc

from quantum_lab_demo.experiments.ids import (
    FLUX_BACKGROUND_RABI_TEMPLATE_ID,
    SPECTATOR_CZ_TEMPLATE_ID,
    SYSTEM_BACKGROUND_RABI_TEMPLATE_ID,
    TWO_QUBIT_GATE_PARAMETER_TABLE,
)

_COUPLER = sc.ScalarType(sc.EntityType(entity_kind="logical_coupler"))
_COUPLER_SERIES = sc.SeriesType(_COUPLER)
_QUANTITY = sc.ScalarType(sc.QuantityType())
_SYSTEM_COUPLER_PARAMETERS = sc.parameter(
    TWO_QUBIT_GATE_PARAMETER_TABLE,
    sc.TableType(
        columns=(
            sc.TableColumn("coupler", _COUPLER),
            sc.TableColumn("coupler_parking_flux", _QUANTITY),
        ),
        allow_extra_columns=True,
    ),
)

_FLUX_COUPLER = sc.input("coupler", _COUPLER)
_FLUX_BIAS = sc.input("flux_bias", _QUANTITY)
FLUX_BACKGROUND_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.background.flux",
        metadata={"template_id": FLUX_BACKGROUND_RABI_TEMPLATE_ID},
    )
    .inputs(_FLUX_COUPLER, _FLUX_BIAS)
    .resource(
        "coupler_bias",
        requires=("set_flux_bias",),
        for_entities=(_FLUX_COUPLER,),
    )
    .bind_field(
        "coupler_bias",
        capability="set_flux_bias",
        field="offset",
        value=_FLUX_BIAS,
    )
    .build()
)

_BACKGROUND_COUPLERS = sc.input("background_couplers", _COUPLER_SERIES)
_SPECTATOR_FLUX_BIAS = sc.input("spectator_flux_bias", _QUANTITY)
SPECTATOR_FLUX_BACKGROUND_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.background.spectator_flux",
        metadata={"template_id": SPECTATOR_CZ_TEMPLATE_ID},
    )
    .inputs(_BACKGROUND_COUPLERS, _SPECTATOR_FLUX_BIAS)
    .resource(
        "spectator_bias",
        requires=("set_flux_bias",),
        for_entities=(_BACKGROUND_COUPLERS,),
    )
    .bind_field(
        "spectator_bias",
        capability="set_flux_bias",
        field="offset",
        value=_SPECTATOR_FLUX_BIAS,
    )
    .build()
)

SYSTEM_COUPLER_PARKING_BACKGROUND_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.background.system_coupler_parking",
        metadata={"template_id": SYSTEM_BACKGROUND_RABI_TEMPLATE_ID},
    )
    .resource(
        "coupler_bias",
        requires=("set_flux_bias",),
    )
    .state_each(
        _SYSTEM_COUPLER_PARAMETERS,
        resource_port="coupler_bias",
        capability="set_flux_bias",
        field="offset",
        value=lambda row: row["coupler_parking_flux"],
        route_entities=(lambda row: row["coupler"],),
    )
    .build()
)

__all__ = [
    "FLUX_BACKGROUND_MODULE",
    "SPECTATOR_FLUX_BACKGROUND_MODULE",
    "SYSTEM_COUPLER_PARKING_BACKGROUND_MODULE",
]

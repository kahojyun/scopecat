"""background-state modules."""

from __future__ import annotations

import scopecat as sc

from quantum_lab_demo.experiments.ids import (
    FLUX_BACKGROUND_RABI_TEMPLATE_ID,
    SPECTATOR_CZ_TEMPLATE_ID,
    SYSTEM_BACKGROUND_RABI_TEMPLATE_ID,
    TWO_QUBIT_GATE_PARAMETER_TABLE,
)

FLUX_BACKGROUND_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.background.flux",
        metadata={"template_id": FLUX_BACKGROUND_RABI_TEMPLATE_ID},
    )
    .input("coupler", value_type=sc.ScalarType(sc.EntityType()))
    .input("flux_bias", value_type=sc.ScalarType(sc.QuantityType()))
    .resource(
        "coupler_bias",
        requires=("set_flux_bias",),
        for_entities=("coupler",),
    )
    .bind("coupler_bias.set_flux_bias.offset", sc.input("flux_bias"))
    .build()
)

SPECTATOR_FLUX_BACKGROUND_MODULE = (
    sc.module(
        "quantum_lab_demo.experiments.background.spectator_flux",
        metadata={"template_id": SPECTATOR_CZ_TEMPLATE_ID},
    )
    .input(
        "background_couplers",
        value_type=sc.SeriesType(sc.ScalarType(sc.EntityType())),
    )
    .input(
        "spectator_flux_bias",
        value_type=sc.ScalarType(sc.QuantityType()),
    )
    .resource(
        "spectator_bias",
        requires=("set_flux_bias",),
        for_entities=("background_couplers",),
    )
    .bind("spectator_bias.set_flux_bias.offset", sc.input("spectator_flux_bias"))
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
        sc.parameter_table(TWO_QUBIT_GATE_PARAMETER_TABLE),
        resource_port="coupler_bias",
        field="set_flux_bias.offset",
        value=sc.col("coupler_parking_flux"),
        route_entities=(sc.col("coupler"),),
    )
    .build()
)

__all__ = [
    "FLUX_BACKGROUND_MODULE",
    "SPECTATOR_FLUX_BACKGROUND_MODULE",
    "SYSTEM_COUPLER_PARKING_BACKGROUND_MODULE",
]

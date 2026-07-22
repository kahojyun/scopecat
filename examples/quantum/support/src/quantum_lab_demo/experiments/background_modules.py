"""background-state modules."""

from __future__ import annotations

from typing import Annotated, cast

import scopecat as sc

from quantum_lab_demo.virtual_lab.parameters import (
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


@sc.module(id="quantum_lab_demo.experiments.background.flux")
def FLUX_BACKGROUND_MODULE(
    coupler: Annotated[sc.Input[str], _COUPLER],
    flux_bias: Annotated[sc.Input[sc.Quantity], _QUANTITY],
):
    coupler_ref = cast("sc.ValueRef", coupler)
    flux_bias_ref = cast("sc.ValueRef", flux_bias)
    return (
        sc.module_body()
        .resource(
            "coupler_bias",
            requires=("set_flux_bias",),
            for_entities=(coupler_ref,),
        )
        .bind_field(
            "coupler_bias",
            capability="set_flux_bias",
            field="offset",
            value=flux_bias_ref,
        )
    )


@sc.module(id="quantum_lab_demo.experiments.background.spectator_flux")
def SPECTATOR_FLUX_BACKGROUND_MODULE(
    background_couplers: Annotated[
        sc.Input[tuple[str, ...]],
        _COUPLER_SERIES,
    ],
    spectator_flux_bias: Annotated[sc.Input[sc.Quantity], _QUANTITY],
):
    couplers_ref = cast("sc.ValueRef", background_couplers)
    flux_bias_ref = cast("sc.ValueRef", spectator_flux_bias)
    return (
        sc.module_body()
        .resource(
            "spectator_bias",
            requires=("set_flux_bias",),
            for_entities=(couplers_ref,),
        )
        .bind_field(
            "spectator_bias",
            capability="set_flux_bias",
            field="offset",
            value=flux_bias_ref,
        )
    )


@sc.module(id="quantum_lab_demo.experiments.background.system_coupler_parking")
def SYSTEM_COUPLER_PARKING_BACKGROUND_MODULE():
    return (
        sc.module_body()
        .resource(
            "coupler_bias",
            requires=("set_flux_bias",),
            for_entities=(_SYSTEM_COUPLER_PARAMETERS.entities("coupler"),),
        )
        .state_each(
            _SYSTEM_COUPLER_PARAMETERS,
            resource_port="coupler_bias",
            capability="set_flux_bias",
            field="offset",
            value=lambda row: row["coupler_parking_flux"],
            target_entities=(lambda row: row["coupler"],),
        )
    )


__all__ = [
    "FLUX_BACKGROUND_MODULE",
    "SPECTATOR_FLUX_BACKGROUND_MODULE",
    "SYSTEM_COUPLER_PARKING_BACKGROUND_MODULE",
]

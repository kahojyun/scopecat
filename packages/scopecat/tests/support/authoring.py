from __future__ import annotations

from pathlib import Path

import scopecat.authoring as authoring
from scopecat.authoring import ExperimentRecipe, ExperimentTemplate
from scopecat.authoring.expressions import ExperimentAsset, linspace
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile
from scopecat.models.parameter import Quantity
from scopecat.models.provider import ProviderOptionDescription

EXAMPLE_DIR = Path(__file__).parents[4] / "fixtures" / "core" / "simple_scan"


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def parameter_build():
    parameter_build = load_config().parameter_build
    assert parameter_build is not None
    return parameter_build


SIMPLE_RECIPE = authoring.recipe(
    id="test.simple_scan",
    experiment_id="authored-simple-scan",
    kind="simple_scan",
    resources=[
        authoring.resource_role("source", authoring.requires("set_frequency")),
    ],
    variables=[
        authoring.sweep(
            "drive_frequency",
            default_span=Quantity(value=200.0, unit="MHz"),
            points=5,
        )
    ],
    bindings=[
        authoring.bind(
            "source.set_frequency.frequency",
            authoring.var_ref("drive_frequency"),
        )
    ],
    dataset=None,
    metadata={"assembled_by": "recipe"},
)


def simple_template() -> ExperimentTemplate:
    return SIMPLE_RECIPE.template(
        label="Simple scan",
        inputs=(
            ProviderOptionDescription(id="subject", dtype="str", required=True),
            ProviderOptionDescription(id="sweep", dtype="AroundSweep | None"),
        ),
    )


def custom_asset_recipe(program: ExperimentAsset | str) -> ExperimentRecipe:
    return authoring.recipe(
        id="custom-echo",
        experiment_id="custom-echo",
        kind="custom",
        resources=[
            authoring.resource_role(
                "source",
                authoring.requires("set_frequency"),
                resource_id="source-0",
            )
        ],
        variables=[
            authoring.variable(
                "drive_frequency",
                linspace(4.9, 5.1, 3, unit="GHz"),
            )
        ],
        bindings=[
            authoring.asset_binding("source.set_frequency.program", program),
        ],
        assets=[program] if isinstance(program, ExperimentAsset) else [],
    )

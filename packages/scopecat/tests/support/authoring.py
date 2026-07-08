from __future__ import annotations

from pathlib import Path

import scopecat.authoring as authoring
from scopecat.authoring import ExperimentTemplate, InputDescription
from scopecat.config_profiles import load_config_profile
from scopecat.models.config import ConfigProfileSnapshot, build_config_parameters
from scopecat.models.parameter import Quantity

EXAMPLE_DIR = Path(__file__).parents[4] / "fixtures" / "core" / "simple_scan"


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def parameter_view():
    return build_config_parameters(load_config())


SIMPLE_MODULE = authoring.module(
    id="test.simple_scan",
    entity_inputs=("subject",),
    resources=[
        authoring.resource_port("source", authoring.requires("set_frequency")),
    ],
    variables=[
        authoring.sweep(
            "drive_frequency",
            default_span=Quantity(value=200.0, unit="MHz"),
            points=5,
            input_id="drive_frequency",
        )
    ],
    bindings=[
        authoring.bind(
            "source.set_frequency.frequency",
            authoring.var_ref("drive_frequency"),
        )
    ],
    records=[authoring.observable("signal", resource="source", unit="ratio")],
    metadata={"assembled_by": "module"},
)


def simple_template() -> ExperimentTemplate:
    return SIMPLE_MODULE.template(
        experiment_id="authored-simple-scan",
        kind="simple_scan",
        label="Simple scan",
        inputs=(
            InputDescription(id="subject", kind="entity"),
            InputDescription(id="drive_frequency", kind="quantity"),
        ),
        defaults={"drive_frequency": None},
    )

from __future__ import annotations

from pathlib import Path

import scopecat.authoring as authoring
from scopecat._parameter_resolution import resolve_config_parameters
from scopecat.authoring import ExperimentTemplate, InputDescription
from scopecat.config_profiles import load_config_profile
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity

EXAMPLE_DIR = Path(__file__).parents[4] / "fixtures" / "core" / "simple_scan"


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def parameters():
    return resolve_config_parameters(load_config()).data


_SIMPLE_SUBJECT = authoring.input(
    "subject",
    authoring.ScalarType(authoring.EntityType()),
)
DRIVE_FREQUENCY_POINT = authoring.point(
    "drive_frequency",
    authoring.ScalarType(authoring.QuantityType(unit="GHz")),
)
SIMPLE_MODULE = (
    authoring.module("test.simple_scan", metadata={"assembled_by": "module"})
    .inputs(_SIMPLE_SUBJECT)
    .resource("source", requires=("set_frequency",))
    .bind(
        "source.set_frequency.frequency",
        DRIVE_FREQUENCY_POINT,
    )
    .record("signal", resource="source", unit="ratio")
    .build()
)


def simple_template() -> ExperimentTemplate:
    return (
        SIMPLE_MODULE.template("test.simple_scan", kind="simple_scan")
        .experiment_id("authored-simple-scan")
        .scan(
            DRIVE_FREQUENCY_POINT,
            center=authoring.parameter(
                "drive_frequency",
                authoring.ScalarType(authoring.QuantityType()),
            ),
            span=Quantity(value=200.0, unit="MHz"),
            points=5,
        )
        .label("Simple scan")
        .inputs(
            InputDescription(id="subject"),
            InputDescription(id="drive_frequency"),
        )
        .metadata(assembled_by="template")
        .build()
    )

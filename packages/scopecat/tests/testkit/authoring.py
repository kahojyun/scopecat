from __future__ import annotations

import scopecat.authoring as authoring
from scopecat.authoring import ExperimentTemplate, InputDescription
from scopecat.config.parameter_resolution import resolve_config_parameters
from scopecat.config.profiles import load_config_profile
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter import Quantity
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR


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
    .resource("source", requires=("set_frequency", "scalar_signal"))
    .bind_field(
        "source",
        capability="set_frequency",
        field="frequency",
        value=DRIVE_FREQUENCY_POINT,
    )
    .product("signal", unit="ratio")
    .acquire(
        "read-signal",
        "signal",
        resource="source",
        capability="scalar_signal",
    )
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
        .record_product("signal")
        .inputs(
            InputDescription(id="subject"),
            InputDescription(id="drive_frequency"),
        )
        .metadata(assembled_by="template")
        .build()
    )

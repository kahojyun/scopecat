from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated

import scopecat.authoring as authoring
from scopecat.authoring import ExperimentTemplate
from scopecat.authoring._products import RecordSelection
from scopecat.authoring._validation import validate_template_definition
from scopecat.authoring.scans import Scan
from scopecat.authoring.values import MetadataValue
from scopecat.config.parameter_resolution import resolve_config_parameters
from scopecat.config.profiles import load_config_profile
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def parameters():
    return resolve_config_parameters(load_config()).data


def template_fixture(
    module: authoring.ExperimentModule,
    *,
    id: str,  # noqa: A002
    kind: str,
    inputs: Sequence[authoring.InputDescription] = (),
    scans: Sequence[Scan] = (),
    records: Sequence[RecordSelection] = (),
    label: str | None = None,
    description: str | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ExperimentTemplate:
    """Build exact-root fixtures for low-level IR and compiler tests."""

    template = ExperimentTemplate(
        id=id,
        kind=kind,
        module=module,
        record_selections=tuple(records),
        inputs=tuple(inputs),
        default_scans=tuple(scans),
        label=label,
        description=description,
        metadata=metadata or {},
    )
    validate_template_definition(
        module=template.module,
        inputs=template.inputs,
        default_scans=template.default_scans,
        record_selections=template.record_selections,
    )
    return template


_SIMPLE_SUBJECT = authoring.input(
    "subject",
    authoring.ScalarType(authoring.EntityType()),
)
DRIVE_FREQUENCY_POINT = authoring.coordinate(
    "drive_frequency",
    authoring.ScalarType(authoring.QuantityType(unit="GHz")),
)
SIMPLE_MODULE = (
    authoring.module_body(id="test.simple_scan", metadata={"assembled_by": "module"})
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
    def definition(
        subject: Annotated[
            authoring.Input[EntityRef | str],
            _SIMPLE_SUBJECT.value_type,
        ],
    ) -> authoring.ExperimentBody:
        module_call = SIMPLE_MODULE(subject=subject)
        return (
            authoring.experiment(module_call)
            .scan(
                DRIVE_FREQUENCY_POINT,
                center=authoring.parameter(
                    "drive_frequency",
                    authoring.ScalarType(authoring.QuantityType()),
                ),
                span=Quantity(value=200.0, unit="MHz"),
                points=5,
            )
            .record_product(module_call.products.signal, record_id="signal")
            .input("drive_frequency")
        )

    return authoring.template(
        id="test.simple_scan",
        kind="simple_scan",
        label="Simple scan",
        metadata={"assembled_by": "template"},
    )(definition)

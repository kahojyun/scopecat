from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, cast

import scopecat.authoring as authoring
from scopecat.authoring import ExperimentInvocation, ExperimentTemplate
from scopecat.authoring._products import RecordSelection
from scopecat.authoring.scans import Scan, axis
from scopecat.authoring.templates import create_experiment_definition_internal
from scopecat.authoring.values import MetadataValue
from scopecat.compiler.frontend.resolution import (
    compile_invocation,
    resolve_compiled_invocation,
)
from scopecat.compiler.linking.linked import LinkedPlan
from scopecat.config.documents import load_config_snapshot_document
from scopecat.config.environment import build_config_environment
from scopecat.config.parameter_resolution import resolve_config_parameters
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.sdk.instruments import InterfaceRef
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR

_SET_FREQUENCY = InterfaceRef("test.set_frequency/v1")
_SET_FREQUENCY_VALUE = _SET_FREQUENCY.property("frequency")
_SCALAR_SIGNAL = InterfaceRef("test.scalar_signal/v1")
_SCALAR_SIGNAL_VALUE = _SCALAR_SIGNAL.acquisition("sample").result("signal")


def load_config() -> ConfigProfileSnapshot:
    return load_config_snapshot_document(EXAMPLE_DIR / "config-snapshot.json")


def parameters():
    return resolve_config_parameters(load_config()).data


def link_invocation(
    invocation: authoring.ExperimentInvocation,
    *,
    config_profile: ConfigProfileSnapshot,
) -> LinkedPlan:
    """Compile and link an authoring fixture against an explicit snapshot."""

    return resolve_compiled_invocation(
        compile_invocation(invocation),
        environment=build_config_environment(config_profile),
    )


def template_fixture(
    module: authoring.ExperimentModule[...],
    *,
    id: str,
    kind: str,
    required_inputs: Sequence[str] = (),
    defaults: Mapping[str, authoring.RuntimeInput] | None = None,
    scans: Sequence[Scan] = (),
    records: Sequence[RecordSelection] = (),
    metadata: Mapping[str, MetadataValue] | None = None,
) -> ExperimentTemplate[...]:
    """Build exact-root fixtures for low-level IR and compiler tests."""

    experiment_definition = create_experiment_definition_internal(
        id=id,
        kind=kind,
        module=module.ir,
        record_selections=tuple(records),
        input_defaults=defaults,
        required_inputs=tuple(required_inputs),
        default_scans=tuple(scans),
        metadata=metadata or {},
    )
    signature = inspect.Signature(
        tuple(
            inspect.Parameter(
                input_definition.id,
                inspect.Parameter.KEYWORD_ONLY,
                default=(
                    input_definition.default
                    if input_definition.has_default
                    else inspect.Parameter.empty
                ),
            )
            for input_definition in experiment_definition.inputs
        )
    )

    def fixture_callable() -> object:
        raise AssertionError("closed test templates are not re-evaluated")

    return ExperimentTemplate(
        definition=experiment_definition,
        _callable=cast("Callable[..., object]", fixture_callable),
        _signature=signature.replace(return_annotation=ExperimentInvocation),
    )


_SIMPLE_SUBJECT = authoring.input(
    "subject",
    authoring.ScalarType(authoring.EntityType()),
)
DRIVE_FREQUENCY_POINT = authoring.coordinate(
    "drive_frequency",
    authoring.ScalarType(authoring.QuantityType(unit="GHz")),
)
SIMPLE_MODULE = (
    authoring.procedure(id="test.simple_scan", metadata={"assembled_by": "module"})
    .inputs(_SIMPLE_SUBJECT)
    .resource(
        "source",
        requires=(_SET_FREQUENCY, _SCALAR_SIGNAL),
    )
    .bind_property(
        "source",
        _SET_FREQUENCY_VALUE,
        value=DRIVE_FREQUENCY_POINT,
    )
    .product("signal", unit="ratio")
    .acquire(
        "read-signal",
        resource="source",
        results={_SCALAR_SIGNAL_VALUE: "signal"},
    )
    .build()
)


def simple_template() -> ExperimentTemplate[...]:
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
                axis(
                    DRIVE_FREQUENCY_POINT,
                    center=authoring.parameter(
                        "drive_frequency",
                        authoring.ScalarType(authoring.QuantityType()),
                    ),
                    span=Quantity(value=200.0, unit="MHz"),
                    points=5,
                ),
            )
            .record_product(module_call.products.signal, record_id="signal")
        )

    return authoring.template(
        id="test.simple_scan",
        kind="simple_scan",
        metadata={"assembled_by": "template"},
    )(definition)

from __future__ import annotations

from typing import Annotated

import scopecat as sc
from scopecat.compiler.frontend.invocation import prepare_invocation
from scopecat.compiler.frontend.resolution import compile_prepared_invocation
from scopecat.config.parameter_resolution import resolve_config_parameters
from scopecat.config.profiles import load_config_profile
from scopecat.records.run_request import (
    AroundScanRecord,
    ParameterAroundScanRecord,
    ParameterScanRecord,
    RunRequest,
    RunRequestAxisValue,
    RunRequestParameterValue,
    parameter_scan_records,
)
from tests.testkit.materialized_effects import materialized_effects_contract
from tests.testkit.paths import CORE_FIXTURE_DIR as SIMPLE_SCAN_FIXTURE
from tests.testkit.workflow_fixtures import load_experiment, load_prepared_invocation


def test_simple_scan_dsl_produces_durable_request_and_user_plan() -> None:
    config = load_config_profile(SIMPLE_SCAN_FIXTURE / "config-profile.json")
    program = load_experiment()
    request = compile_prepared_invocation(load_prepared_invocation()).request

    restored_request = RunRequest.model_validate_json(request.model_dump_json())
    assert restored_request == request
    centered_scan = request.scans[0]
    assert isinstance(centered_scan, AroundScanRecord)
    assert centered_scan.center == RunRequestParameterValue(
        parameter_id="drive_frequency"
    )

    preview = materialized_effects_contract(
        program,
        resolve_config_parameters(config).data,
        config=config,
    )
    assert len(preview.points) == 3


def test_parameter_scan_request_materializes_typed_input_keys() -> None:
    subject = sc.input("subject", sc.ScalarType(sc.EntityType()))
    frequency = sc.coordinate(
        "frequency",
        sc.ScalarType(sc.QuantityType(unit="GHz")),
    )
    module = sc.module_body(id="test.request_keys").inputs(subject).build()

    @sc.template(id="test.request_keys", kind="request_keys")
    def template_definition(
        subject: Annotated[
            sc.Input[sc.EntityRef | str],
            sc.ScalarType(sc.EntityType()),
        ],
    ) -> sc.ExperimentBody:
        return sc.experiment(module(subject=subject))

    template = template_definition
    invocation = template.bind(subject="q0").scan(
        sc.param_axis(
            frequency,
            sc.param_row("device_parameters", subject=subject),
            "frequency",
            [4.9, 5.1],
            unit="GHz",
        )
    )

    request = compile_prepared_invocation(prepare_invocation(invocation)).request

    parameter_scan = request.scans[0]
    assert isinstance(parameter_scan, ParameterScanRecord)
    assert parameter_scan.key == {"subject": "q0"}


def test_parameter_around_scan_request_preserves_implicit_center_intent() -> None:
    subject = sc.input("subject", sc.ScalarType(sc.EntityType()))
    frequency = sc.coordinate(
        "frequency",
        sc.ScalarType(sc.QuantityType(unit="GHz")),
    )
    module = sc.module_body(id="test.request_parameter_around").inputs(subject).build()

    @sc.template(id="test.request_parameter_around", kind="request_keys")
    def template_definition(
        subject: Annotated[
            sc.Input[sc.EntityRef | str],
            sc.ScalarType(sc.EntityType()),
        ],
    ) -> sc.ExperimentBody:
        return sc.experiment(module(subject=subject))

    template = template_definition
    invocation = template.bind(subject="q0").scan(
        sc.param_axis(
            frequency,
            sc.param_row("device_parameters", subject=subject),
            "frequency",
            span=sc.Quantity(200, "MHz"),
            points=5,
        )
    )

    request = compile_prepared_invocation(prepare_invocation(invocation)).request

    parameter_scan = request.scans[0]
    assert isinstance(parameter_scan, ParameterAroundScanRecord)
    assert parameter_scan.key == {"subject": "q0"}
    assert parameter_scan.span == sc.Quantity(200, "MHz")
    assert parameter_scan.points == 5
    assert parameter_scan_records(request.scans) == [parameter_scan]
    assert RunRequest.model_validate_json(request.model_dump_json()) == request


def test_dependent_default_scan_projects_its_input_as_an_axis() -> None:
    frequency = sc.ScalarType(sc.QuantityType(unit="GHz"))
    first_axis = sc.coordinate("first", frequency)
    second_axis = sc.coordinate("second", frequency)
    module = sc.module_body(id="test.request_axis_dependency").build()

    @sc.template(
        id="test.request_axis_dependency",
        kind="request_axis_dependency",
    )
    def template_definition(
        first: Annotated[sc.Input[sc.Quantity], sc.QuantityType(unit="GHz")],
    ) -> sc.ExperimentBody:
        return (
            sc.experiment(module())
            .scan(
                second_axis,
                center=first,
                span="2 GHz",
                points=2,
            )
            .scan(first_axis, [4.9, 5.1], unit="GHz")
        )

    template = template_definition

    compiled = compile_prepared_invocation(prepare_invocation(template.bind()))

    centered = compiled.request.scans[0]
    assert isinstance(centered, AroundScanRecord)
    assert centered.center == RunRequestAxisValue(axis_id="first")
    assert set(compiled.assembly.source.inputs) == {"first"}

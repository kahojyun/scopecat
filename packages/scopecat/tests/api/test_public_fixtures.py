from __future__ import annotations

from typing import Annotated

import scopecat as sc
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.config.documents import load_config_snapshot_document
from scopecat.config.parameter_resolution import resolve_config_parameters
from scopecat.records.run_request import (
    AroundScanRecord,
    ParameterAroundScanRecord,
    ParameterScanRecord,
    PointScanRecord,
    RunRequest,
    RunRequestParameterValue,
)
from tests.testkit.materialized_effects import materialized_effects_contract
from tests.testkit.paths import CORE_FIXTURE_DIR as SIMPLE_SCAN_FIXTURE
from tests.testkit.workflow_fixtures import load_experiment, load_invocation


def test_cartesian_scan_request_contains_only_flat_axis_records() -> None:
    first = sc.coordinate("first", sc.ScalarType(sc.IntType()))
    second = sc.coordinate("second", sc.ScalarType(sc.IntType()))
    module = sc.module_body(id="test.request_cartesian").build()

    @sc.template(id="test.request_cartesian", kind="request_cartesian")
    def template_definition() -> sc.ExperimentBody:
        return sc.experiment(module()).scan(
            sc.cartesian(sc.axis(first, [1, 2]), sc.axis(second, [3, 4]))
        )

    request = compile_invocation(template_definition.bind()).request

    assert all(isinstance(scan, PointScanRecord) for scan in request.scans)
    assert [scan.axis_id for scan in request.scans] == ["first", "second"]


def test_simple_scan_dsl_produces_durable_request_and_user_plan() -> None:
    config = load_config_snapshot_document(SIMPLE_SCAN_FIXTURE / "config-snapshot.json")
    program = load_experiment()
    request = compile_invocation(load_invocation()).request

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
    frequency_type = sc.ScalarType(sc.QuantityType(unit="GHz"))
    frequency = sc.coordinate("frequency", frequency_type)
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
            sc.parameter_lookup(
                "device_parameters",
                key={"subject": subject},
                column="frequency",
                value_type=frequency_type,
            ),
            [4.9, 5.1],
            unit="GHz",
        )
    )

    request = compile_invocation(invocation).request

    parameter_scan = request.scans[0]
    assert isinstance(parameter_scan, ParameterScanRecord)
    assert parameter_scan.key == {"subject": "q0"}


def test_parameter_around_scan_request_preserves_implicit_center_intent() -> None:
    subject = sc.input("subject", sc.ScalarType(sc.EntityType()))
    frequency_type = sc.ScalarType(sc.QuantityType(unit="GHz"))
    frequency = sc.coordinate("frequency", frequency_type)
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
            sc.parameter_lookup(
                "device_parameters",
                key={"subject": subject},
                column="frequency",
                value_type=frequency_type,
            ),
            span=sc.Quantity(200, "MHz"),
            points=5,
        )
    )

    request = compile_invocation(invocation).request

    parameter_scan = request.scans[0]
    assert isinstance(parameter_scan, ParameterAroundScanRecord)
    assert parameter_scan.key == {"subject": "q0"}
    assert parameter_scan.span == sc.Quantity(200, "MHz")
    assert parameter_scan.points == 5
    assert RunRequest.model_validate_json(request.model_dump_json()) == request


def test_bound_default_scan_center_projects_as_a_closed_value() -> None:
    frequency = sc.ScalarType(sc.QuantityType(unit="GHz"))
    first_axis = sc.coordinate("first", frequency)
    second_axis = sc.coordinate("second", frequency)
    module = sc.module_body(id="test.request_axis_dependency").build()

    @sc.template(
        id="test.request_axis_dependency",
        kind="request_axis_dependency",
    )
    def template_definition(
        first: Annotated[
            sc.Input[sc.Quantity],
            sc.ScalarType(sc.QuantityType(unit="GHz")),
        ],
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

    compiled = compile_invocation(
        template.bind(first=sc.Quantity(value=5.0, unit="GHz"))
    )

    centered = compiled.request.scans[0]
    assert isinstance(centered, AroundScanRecord)
    assert centered.center == sc.Quantity(value=5.0, unit="GHz")
    assert set(compiled.assembly.source.inputs) == {"first"}

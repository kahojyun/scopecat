from __future__ import annotations

import scopecat as sc
from scopecat.compiler.frontend.invocation import prepare_invocation
from scopecat.compiler.frontend.resolution import compile_prepared_invocation
from scopecat.config.parameter_resolution import resolve_config_parameters
from scopecat.config.profiles import load_config_profile
from scopecat.records.run_request import (
    AroundScanRecord,
    ParameterScanRecord,
    RunRequest,
    RunRequestParameterValue,
)
from tests.testkit.bound_plan import bound_plan_contract
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
    assert "param_scalar" not in request.model_dump_json()

    preview = bound_plan_contract(
        program,
        resolve_config_parameters(config).data,
        config=config,
    )
    assert preview.point_count == 3
    assert preview.product_uses


def test_parameter_scan_request_materializes_typed_input_keys() -> None:
    subject = sc.input("subject", sc.ScalarType(sc.EntityType()))
    frequency = sc.point(
        "frequency",
        sc.ScalarType(sc.QuantityType(unit="GHz")),
    )
    module = sc.module("test.request_keys").inputs(subject).build()
    template = module.template("test.request_keys", kind="request_keys").build()
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
    assert "source_kind" not in request.model_dump_json()

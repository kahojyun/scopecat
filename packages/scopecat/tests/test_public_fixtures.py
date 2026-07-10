from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat._parameter_resolution import resolve_config_parameters
from scopecat.authoring._invocation_plan import prepare_invocation
from scopecat.authoring._resolution import compile_prepared_invocation
from scopecat.config_profiles import load_config_profile
from scopecat.models.run_request import (
    AroundScanRecord,
    ParameterScanRecord,
    RunRequest,
    RunRequestParameterValue,
)
from tests.support.experiment_preview import preview_contract
from tests.support.workflow_fixtures import load_experiment, load_prepared_invocation

REPO_ROOT = Path(__file__).parents[3]
FIXTURE_ROOT = REPO_ROOT / "fixtures"
SIMPLE_SCAN_FIXTURE = FIXTURE_ROOT / "core" / "simple_scan"


def test_public_fixtures_do_not_persist_compiler_programs() -> None:
    assert not list(FIXTURE_ROOT.glob("**/experiment.json"))


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

    preview = preview_contract(
        program,
        resolve_config_parameters(config).data,
        config=config,
    )
    assert preview.point_count == 3
    assert preview.records


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

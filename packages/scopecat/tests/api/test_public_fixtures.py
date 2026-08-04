from __future__ import annotations

from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.config.documents import load_config_snapshot_document
from scopecat.config.parameter_resolution import resolve_config_parameters
from scopecat.records.run_request import (
    AroundScanRecord,
    GridDomainRecord,
    RunRequest,
    RunRequestParameterValue,
)
from tests.testkit.materialized_effects import materialized_effects_contract
from tests.testkit.paths import CORE_FIXTURE_DIR as SIMPLE_SCAN_FIXTURE
from tests.testkit.workflow_fixtures import load_experiment, load_invocation


def test_public_scan_slice_produces_a_durable_request_and_plan() -> None:
    config = load_config_snapshot_document(SIMPLE_SCAN_FIXTURE / "config-snapshot.json")
    request = compile_invocation(load_invocation()).request

    assert RunRequest.model_validate_json(request.model_dump_json()) == request
    assert isinstance(request.point_plan.domain, GridDomainRecord)
    centered_scan = request.point_plan.domain.axes[0]
    assert isinstance(centered_scan, AroundScanRecord)
    assert centered_scan.center == RunRequestParameterValue(
        parameter_id="drive_frequency"
    )

    preview = materialized_effects_contract(
        load_experiment(),
        resolve_config_parameters(config).data,
        config=config,
    )
    assert len(preview.points) == 3

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.run_plan import build_run_plan_record
from scopecat._storage.refs import RUN_PLAN_REF, RUN_REQUEST_REF
from scopecat._workflows.compilation import compile_experiment
from scopecat._workflows.runs import load_run_plan, load_run_request, start_run
from scopecat.authoring._resolution import compile_prepared_invocation
from scopecat.errors import DataIntegrityError
from scopecat.models.run_plan import RunPlanRecord
from scopecat.models.run_request import RunRequest
from scopecat.runs import open_run_store
from tests.support.signal_instruments import TestSignalInstrumentProvider
from tests.support.workflow_fixtures import load_config, load_prepared_invocation

FIXTURE_DIR = Path(__file__).with_name("fixtures")


def _golden(name: str) -> dict[str, Any]:
    return cast(
        "dict[str, Any]",
        json.loads((FIXTURE_DIR / name).read_text()),
    )


def _all_mapping_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        mapping = cast("dict[object, object]", value)
        return {
            *(key for key in mapping if isinstance(key, str)),
            *(
                nested_key
                for item in mapping.values()
                for nested_key in _all_mapping_keys(item)
            ),
        }
    if isinstance(value, list):
        sequence = cast("list[object]", value)
        return {
            nested_key for item in sequence for nested_key in _all_mapping_keys(item)
        }
    return set()


def _canonical_projections(workspace: Path) -> tuple[RunRequest, RunPlanRecord]:
    """Project the canonical simple-scan DSL and config through the real pipeline."""

    compiled_invocation = compile_prepared_invocation(load_prepared_invocation())
    environment = validate_config_environment(load_config())
    assert environment.valid, environment.problems
    compiled_experiment = compile_experiment(
        compiled_invocation,
        environment=environment,
        workspace=workspace,
    )
    assert compiled_experiment.valid, compiled_experiment.problems
    return (
        compiled_experiment.request,
        build_run_plan_record(compiled_experiment.plan),
    )


def test_run_request_v4_projector_matches_golden_and_round_trips(
    tmp_path: Path,
) -> None:
    golden = _golden("run-request-v4.json")
    request, _plan = _canonical_projections(tmp_path)

    restored = RunRequest.model_validate_json(json.dumps(golden))

    assert request.schema_version == "scopecat.run_request.v4"
    assert request.model_dump(mode="json") == golden
    assert restored == request


def test_run_plan_v3_projector_matches_golden_and_round_trips(
    tmp_path: Path,
) -> None:
    golden = _golden("run-plan-v3.json")
    _request, plan = _canonical_projections(tmp_path)

    restored = RunPlanRecord.model_validate_json(json.dumps(golden))

    assert plan.schema_version == "scopecat.run_plan_record.v3"
    assert plan.model_dump(mode="json") == golden
    assert restored == plan
    assert plan.state_changes[0].capability_id == "set_frequency"
    assert plan.state_changes[0].field_path == "frequency"


def test_durable_goldens_exclude_transient_compiler_identity() -> None:
    forbidden_keys = {
        "compute_node_id",
        "node_id",
        "origin",
        "producer_id",
        "program_graph",
    }

    request_keys = _all_mapping_keys(_golden("run-request-v4.json"))
    plan_keys = _all_mapping_keys(_golden("run-plan-v3.json"))

    assert request_keys.isdisjoint(forbidden_keys)
    assert plan_keys.isdisjoint(forbidden_keys)


@pytest.mark.parametrize(
    "corruption",
    [
        "legacy_schema",
        "compiler_root",
        "unknown_scan_kind",
        "symbolic_node_identity",
        "missing_scan_values",
    ],
)
def test_corrupt_run_request_is_rejected(
    corruption: str,
) -> None:
    request = deepcopy(_golden("run-request-v4.json"))
    if corruption == "legacy_schema":
        request["schema_version"] = "scopecat.run_request.v3"
    elif corruption == "compiler_root":
        request["compiled_program"] = {"nodes": []}
    elif corruption == "unknown_scan_kind":
        request["scans"][0]["kind"] = "compute"
    elif corruption == "symbolic_node_identity":
        request["scans"][0]["center"]["node_id"] = "produce"
    elif corruption == "missing_scan_values":
        del request["scans"][0]["points"]
    else:  # pragma: no cover - parametrization is closed above
        raise AssertionError(corruption)

    with pytest.raises(ValidationError):
        RunRequest.model_validate(request)


@pytest.mark.parametrize(
    "corruption",
    [
        "legacy_schema",
        "compiler_root",
        "legacy_state_field",
        "deferred_node_identity",
        "out_of_range_state",
    ],
)
def test_corrupt_run_plan_is_rejected(
    corruption: str,
) -> None:
    plan = deepcopy(_golden("run-plan-v3.json"))
    if corruption == "legacy_schema":
        plan["schema_version"] = "scopecat.run_plan_record.v2"
    elif corruption == "compiler_root":
        plan["program_graph"] = {"nodes": []}
    elif corruption == "legacy_state_field":
        state_change = plan["state_changes"][0]
        del state_change["capability_id"]
        del state_change["field_path"]
        state_change["field"] = "set.frequency.value.path"
    elif corruption == "deferred_node_identity":
        plan["state_changes"][0]["after"] = {
            "kind": "deferred",
            "node_id": "produce",
        }
    elif corruption == "out_of_range_state":
        plan["state_changes"][0]["point_index"] = plan["point_count"]
    else:  # pragma: no cover - parametrization is closed above
        raise AssertionError(corruption)

    with pytest.raises(ValidationError):
        RunPlanRecord.model_validate(plan)


def test_stored_plan_remains_readable_when_stored_request_is_corrupt(
    tmp_path: Path,
) -> None:
    run = start_run(
        instrument_provider=TestSignalInstrumentProvider(),
        config=load_config(),
        experiment=load_prepared_invocation(),
        workspace=tmp_path,
    )
    storage = open_run_store(tmp_path)
    request_path = storage.ref_path(run.run_id, RUN_REQUEST_REF)
    request = cast("dict[str, Any]", json.loads(request_path.read_text()))
    request["schema_version"] = "scopecat.run_request.v3"
    request_path.write_text(json.dumps(request))

    with pytest.raises(DataIntegrityError):
        load_run_request(run_id=run.run_id, workspace=tmp_path)

    plan = load_run_plan(run_id=run.run_id, workspace=tmp_path)
    assert plan.model_dump(mode="json") == _golden("run-plan-v3.json")


def test_stored_request_remains_readable_when_stored_plan_is_corrupt(
    tmp_path: Path,
) -> None:
    run = start_run(
        instrument_provider=TestSignalInstrumentProvider(),
        config=load_config(),
        experiment=load_prepared_invocation(),
        workspace=tmp_path,
    )
    storage = open_run_store(tmp_path)
    plan_path = storage.ref_path(run.run_id, RUN_PLAN_REF)
    plan = cast("dict[str, Any]", json.loads(plan_path.read_text()))
    plan["schema_version"] = "scopecat.run_plan_record.v2"
    plan_path.write_text(json.dumps(plan))

    with pytest.raises(DataIntegrityError):
        load_run_plan(run_id=run.run_id, workspace=tmp_path)

    request = load_run_request(run_id=run.run_id, workspace=tmp_path)
    assert request is not None
    assert request.model_dump(mode="json") == _golden("run-request-v4.json")

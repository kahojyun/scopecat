from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import TypeAdapter, ValidationError

from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.run_plan import build_run_plan_record
from scopecat._relation_backend import ReferenceRelationBackend
from scopecat._resource_identity import LogicalResourcePortId, PhysicalResourceId
from scopecat._storage.refs import RUN_PLAN_REF, RUN_REQUEST_REF
from scopecat._workflows.compilation import compile_experiment
from scopecat._workflows.preview import build_experiment_preview
from scopecat._workflows.runs import load_run_plan, load_run_request, start_run
from scopecat.authoring._resolution import compile_prepared_invocation
from scopecat.errors import DataIntegrityError
from scopecat.models.run_plan import RunPlanRecord
from scopecat.models.run_request import RunRequest
from scopecat.preview import ExperimentPreview
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


def _assert_no_nominal_resource_ids(value: object) -> None:
    assert not isinstance(value, LogicalResourcePortId | PhysicalResourceId)
    if isinstance(value, dict):
        for key, item in cast("dict[object, object]", value).items():
            _assert_no_nominal_resource_ids(key)
            _assert_no_nominal_resource_ids(item)
    elif isinstance(value, list | tuple):
        for item in cast("list[object] | tuple[object, ...]", value):
            _assert_no_nominal_resource_ids(item)


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


def test_run_plan_v4_projector_matches_golden_and_round_trips(
    tmp_path: Path,
) -> None:
    golden = _golden("run-plan-v4.json")
    _request, plan = _canonical_projections(tmp_path)

    restored = RunPlanRecord.model_validate_json(json.dumps(golden))

    assert plan.schema_version == "scopecat.run_plan_record.v4"
    assert plan.model_dump(mode="json") == golden
    assert restored == plan
    assert plan.state_changes[0].capability_id == "set_frequency"
    assert plan.state_changes[0].field_path == "frequency"
    assert plan.state_changes[0].resource_id == "source-0"
    assert plan.records[0].resource_port_id == "source"
    assert plan.records[0].physical_resource_id is None


def test_preview_and_run_plan_resource_projections_are_repeatable_and_plain(
    tmp_path: Path,
) -> None:
    invocation = compile_prepared_invocation(load_prepared_invocation())
    environment = validate_config_environment(load_config())

    compiled_first = compile_experiment(
        invocation,
        environment=environment,
        workspace=tmp_path / "first",
    )
    compiled_second = compile_experiment(
        invocation,
        environment=environment,
        workspace=tmp_path / "second",
    )
    assert compiled_first.valid, compiled_first.problems
    assert compiled_second.valid, compiled_second.problems

    preview_adapter = TypeAdapter(ExperimentPreview)
    preview_first = preview_adapter.dump_python(
        build_experiment_preview(compiled_first.plan),
        mode="json",
    )
    preview_second = preview_adapter.dump_python(
        build_experiment_preview(compiled_second.plan),
        mode="json",
    )
    plan_first = build_run_plan_record(compiled_first.plan).model_dump(mode="json")
    plan_second = build_run_plan_record(compiled_second.plan).model_dump(mode="json")

    assert preview_first == preview_second
    assert plan_first == plan_second
    assert json.dumps(preview_first, sort_keys=True) == json.dumps(
        preview_second,
        sort_keys=True,
    )
    assert json.dumps(plan_first, sort_keys=True) == json.dumps(
        plan_second,
        sort_keys=True,
    )
    _assert_no_nominal_resource_ids(preview_first)
    _assert_no_nominal_resource_ids(plan_first)


def test_compilation_workflow_threads_the_selected_relation_backend(
    tmp_path: Path,
) -> None:
    compiled_invocation = compile_prepared_invocation(load_prepared_invocation())
    environment = validate_config_environment(load_config())
    backend = ReferenceRelationBackend(backend_id="tests.workflow-reference")

    compiled = compile_experiment(
        compiled_invocation,
        environment=environment,
        workspace=tmp_path,
        relation_backend=backend,
    )

    assert compiled.valid
    assert compiled.plan.relation_backend_id == "tests.workflow-reference"


def test_durable_goldens_exclude_transient_compiler_identity() -> None:
    forbidden_keys = {
        "compute_node_id",
        "entity_uses",
        "key_uses",
        "node_id",
        "origin",
        "producer_id",
        "program_graph",
        "relation_use",
        "relation_use_id",
        "resource_use",
        "route_entity_uses",
        "value_use",
    }

    request_keys = _all_mapping_keys(_golden("run-request-v4.json"))
    plan_keys = _all_mapping_keys(_golden("run-plan-v4.json"))

    assert request_keys.isdisjoint(forbidden_keys)
    assert plan_keys.isdisjoint(forbidden_keys)
    assert plan_keys.isdisjoint({"fixed_resource", "resource"})


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
        "ambiguous_record_target",
        "deferred_node_identity",
        "out_of_range_state",
    ],
)
def test_corrupt_run_plan_is_rejected(
    corruption: str,
) -> None:
    plan = deepcopy(_golden("run-plan-v4.json"))
    if corruption == "legacy_schema":
        plan["schema_version"] = "scopecat.run_plan_record.v3"
    elif corruption == "compiler_root":
        plan["program_graph"] = {"nodes": []}
    elif corruption == "legacy_state_field":
        state_change = plan["state_changes"][0]
        del state_change["capability_id"]
        del state_change["field_path"]
        state_change["field"] = "set.frequency.value.path"
    elif corruption == "ambiguous_record_target":
        plan["records"][0]["physical_resource_id"] = "source-0"
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
    assert plan.model_dump(mode="json") == _golden("run-plan-v4.json")


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
    plan["schema_version"] = "scopecat.run_plan_record.v3"
    plan_path.write_text(json.dumps(plan))

    with pytest.raises(DataIntegrityError):
        load_run_plan(run_id=run.run_id, workspace=tmp_path)

    request = load_run_request(run_id=run.run_id, workspace=tmp_path)
    assert request is not None
    assert request.model_dump(mode="json") == _golden("run-request-v4.json")

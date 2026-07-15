from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import TypeAdapter, ValidationError

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.frontend.resolution import compile_prepared_invocation
from scopecat.compiler.linking.linked import link_program
from scopecat.compiler.pipeline import compile_experiment
from scopecat.compiler.relations.reference_backend import ReferenceRelationBackend
from scopecat.composition.local import local_run_repository, local_workspace_services
from scopecat.kernel.errors import DataIntegrityError
from scopecat.planning.backend import ExecutionBackend
from scopecat.planning.preview import build_experiment_preview
from scopecat.planning.preview_models import ExperimentPreview
from scopecat.records.run_plan import (
    RunPlanPointInstrumentExecution,
    RunPlanRecord,
)
from scopecat.records.run_request import RunRequest
from scopecat.runs.refs import RUN_PLAN_REF, RUN_REQUEST_REF
from scopecat.runs.service import load_run_plan, load_run_request, start_run
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import load_config, load_prepared_invocation

FIXTURE_DIR = Path(__file__).with_name("fixtures")


def _point_execution() -> RunPlanPointInstrumentExecution:
    return RunPlanPointInstrumentExecution(
        unit_id="point-instrument",
        backend_id="scopecat.execution.v2",
        provider_id="tests.signal_instrument_provider",
    )


def _golden(name: str) -> dict[str, Any]:
    return cast(
        "dict[str, Any]",
        json.loads((FIXTURE_DIR / name).read_text()),
    )


def _canonical_projections(workspace: Path) -> tuple[RunRequest, RunPlanRecord]:
    """Project the canonical simple-scan DSL and config through the real pipeline."""

    compiled_invocation = compile_prepared_invocation(load_prepared_invocation())
    environment = validate_config_environment(load_config())
    assert environment.valid, environment.problems
    compiled_experiment = compile_experiment(
        compiled_invocation,
        environment=environment,
    )
    assert compiled_experiment.valid, compiled_experiment.problems
    return (
        compiled_experiment.request,
        ExecutionBackend(provider=TestSignalInstrumentProvider())
        .prepare(
            link_program(compiled_experiment.program, environment),
            config=load_config(),
        )
        .run_plan_record(),
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


def test_run_plan_v9_projector_matches_golden_and_round_trips(
    tmp_path: Path,
) -> None:
    golden = _golden("run-plan-v9.json")
    _request, plan = _canonical_projections(tmp_path)

    restored = RunPlanRecord.model_validate_json(json.dumps(golden))

    assert plan.schema_version == "scopecat.run_plan_record.v9"
    assert plan.model_dump(mode="json") == golden
    assert restored == plan
    assert plan.backend_id == "scopecat.execution.v2"
    assert plan.execution_options.requested.fusion == "automatic"
    assert plan.execution_options.resolved.fusion == "disabled"
    assert plan.execution_options.resolved.max_points_per_batch == 1
    assert plan.execution_units == [_point_execution()]
    assert plan.records[0].producer_unit_id == "point-instrument"
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
    )
    compiled_second = compile_experiment(
        invocation,
        environment=environment,
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
    backend = ExecutionBackend(provider=TestSignalInstrumentProvider())
    plan_first = (
        backend.prepare(
            link_program(compiled_first.program, environment),
            config=load_config(),
        )
        .run_plan_record()
        .model_dump(mode="json")
    )
    plan_second = (
        backend.prepare(
            link_program(compiled_second.program, environment),
            config=load_config(),
        )
        .run_plan_record()
        .model_dump(mode="json")
    )

    assert preview_first == preview_second
    assert plan_first == plan_second


def test_compilation_workflow_threads_the_selected_relation_backend(
    tmp_path: Path,
) -> None:
    compiled_invocation = compile_prepared_invocation(load_prepared_invocation())
    environment = validate_config_environment(load_config())
    backend = ReferenceRelationBackend(backend_id="tests.workflow-reference")

    compiled = compile_experiment(
        compiled_invocation,
        environment=environment,
        relation_backend=backend,
    )

    assert compiled.valid
    assert compiled.plan.relation_backend_id == "tests.workflow-reference"


@pytest.mark.parametrize(
    "corruption",
    [
        "unknown_scan_kind",
        "missing_scan_values",
    ],
)
def test_corrupt_run_request_is_rejected(
    corruption: str,
) -> None:
    request = deepcopy(_golden("run-request-v4.json"))
    if corruption == "unknown_scan_kind":
        request["scans"][0]["kind"] = "compute"
    elif corruption == "missing_scan_values":
        del request["scans"][0]["points"]
    else:  # pragma: no cover - parametrization is closed above
        raise AssertionError(corruption)

    with pytest.raises(ValidationError):
        RunRequest.model_validate(request)


@pytest.mark.parametrize(
    "corruption",
    [
        "ambiguous_record_target",
        "missing_backend_id",
        "missing_execution_options",
        "missing_execution_units",
        "out_of_range_state",
    ],
)
def test_corrupt_run_plan_is_rejected(
    corruption: str,
) -> None:
    plan = deepcopy(_golden("run-plan-v9.json"))
    if corruption == "ambiguous_record_target":
        plan["records"][0]["physical_resource_id"] = "source-0"
    elif corruption == "missing_backend_id":
        del plan["backend_id"]
    elif corruption == "missing_execution_options":
        del plan["execution_options"]
    elif corruption == "missing_execution_units":
        del plan["execution_units"]
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
        execution_backend=ExecutionBackend(provider=TestSignalInstrumentProvider()),
        config=load_config(),
        experiment=load_prepared_invocation(),
        services=local_workspace_services(tmp_path),
    )
    storage = local_run_repository(tmp_path)
    request_path = storage.ref_path(run.run_id, RUN_REQUEST_REF)
    request = cast("dict[str, Any]", json.loads(request_path.read_text()))
    request["schema_version"] = "scopecat.run_request.v3"
    request_path.write_text(json.dumps(request))

    with pytest.raises(DataIntegrityError):
        load_run_request(
            run_id=run.run_id,
            services=local_workspace_services(tmp_path),
        )

    plan = load_run_plan(
        run_id=run.run_id,
        services=local_workspace_services(tmp_path),
    )
    assert plan.model_dump(mode="json") == _golden("run-plan-v9.json")


def test_stored_request_remains_readable_when_stored_plan_is_corrupt(
    tmp_path: Path,
) -> None:
    run = start_run(
        execution_backend=ExecutionBackend(provider=TestSignalInstrumentProvider()),
        config=load_config(),
        experiment=load_prepared_invocation(),
        services=local_workspace_services(tmp_path),
    )
    storage = local_run_repository(tmp_path)
    plan_path = storage.ref_path(run.run_id, RUN_PLAN_REF)
    plan = cast("dict[str, Any]", json.loads(plan_path.read_text()))
    plan["schema_version"] = "scopecat.run_plan_record.v3"
    plan_path.write_text(json.dumps(plan))

    with pytest.raises(DataIntegrityError):
        load_run_plan(
            run_id=run.run_id,
            services=local_workspace_services(tmp_path),
        )

    request = load_run_request(
        run_id=run.run_id,
        services=local_workspace_services(tmp_path),
    )
    assert request is not None
    assert request.model_dump(mode="json") == _golden("run-request-v4.json")

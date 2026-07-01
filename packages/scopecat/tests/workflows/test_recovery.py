from __future__ import annotations

from scopecat.experiments import PlanSnapshot, acquire, experiment, plan_experiment
from scopecat.relations import ParameterRelationData, grid
from scopecat.workflows import build_run_resume_manifest, plan_run_resume
from tests.support.records import assert_model_round_trip


def test_plan_run_resume_selects_pending_and_retry_points() -> None:
    plan = _plan()
    original_content_hash = plan.content_hash

    resume = plan_run_resume(
        plan,
        [
            {"point_id": 0, "status": "ok"},
            {"point_id": 1, "status": "failed"},
            {"point_id": 3, "status": "skipped"},
        ],
    )
    manifest = build_run_resume_manifest(
        run_id="run-000001",
        plan=plan,
        resume=resume,
        status_ref="artifacts/point-status.jsonl",
    )

    assert_model_round_trip(resume, schema_version="scopecat.run_resume_plan.v1")
    assert_model_round_trip(
        manifest,
        schema_version="scopecat.run_resume_manifest.v1",
    )
    assert resume.completed_point_ids == [0]
    assert resume.retry_point_ids == [1]
    assert resume.pending_point_ids == [1, 2]
    assert manifest.pending_point_ids == resume.pending_point_ids
    assert plan.content_hash == original_content_hash


def _plan() -> PlanSnapshot:
    spec = experiment(
        id="resume-boundary",
        kind="workflow.resume",
        points=grid(point=[0, 1, 2, 3]),
        acquire=acquire("measurement"),
    )
    return plan_experiment(spec, params=ParameterRelationData())

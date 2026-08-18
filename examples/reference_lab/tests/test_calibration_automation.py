from __future__ import annotations

import shutil
from pathlib import Path

from scopecat.api.procedure_worker import ProjectProcedureWorkerLoop
from scopecat.automation import ConfigPublishOutputRef
from scopecat.project import load_project
from scopecat_server.lifecycle import start_project, stop_project

from reference_lab.application import create_application
from reference_lab.configuration import EXAMPLE_ROOT
from reference_lab.workflows.drag_beta_freshness import (
    DRAG_BETA_CALIBRATION_FANOUT_SCOPE,
)


def test_calibration_cohort_survives_restart_and_becomes_fresh(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "reference-lab-calibration"
    shutil.copytree(EXAMPLE_ROOT / "config", project_root / "config")
    shutil.copytree(EXAMPLE_ROOT / "src", project_root / "src")
    shutil.copy2(EXAMPLE_ROOT / "scopecat.toml", project_root / "scopecat.toml")
    project = load_project(project_root / "scopecat.toml")

    first_record = start_project(project)
    try:
        with create_application(project_root).connect(first_record.base_url) as lab:
            active_before = lab.config.active()

            admitted = lab.calibrations.evaluator().cycle()

            assert admitted.selected_targets == 2
            assert admitted.ready_members == 2
            assert admitted.admitted_members == 2
            assert admitted.created_cohorts == 1
            assert admitted.failures == 0
            [summary] = lab.calibrations.list(
                fanout_scope=DRAG_BETA_CALIBRATION_FANOUT_SCOPE
            ).items
            cohort = lab.calibrations.get(summary.cohort_id)
            member_page = lab.calibrations.members(cohort.cohort_id)
            assert member_page.next_cursor is None
            assert tuple(member.index for member in member_page.items) == (0, 1)
            assert tuple(member.spec.target.id for member in member_page.items) == (
                "q0",
                "q1",
            )
            procedure_run_ids = tuple(
                member.procedure_run_id for member in member_page.items
            )
            assert len(set(procedure_run_ids)) == 2
            assert all(
                lab.procedures.get(procedure_run_id).state == "ready"
                for procedure_run_id in procedure_run_ids
            )

        stopped = stop_project(project)
        assert stopped.state == "running"
        restarted_record = start_project(project)

        with create_application(project_root).connect(restarted_record.base_url) as lab:
            worker = ProjectProcedureWorkerLoop(
                lab.procedures,
                calibration_evaluator=lab.calibrations.evaluator(),
                worker_id="reference-lab-calibration-after-restart",
                runnable_limit=2,
            )

            completed = worker.cycle()

            assert completed.suppressed_active_calibrations == 2
            assert completed.admitted_calibrations == 0
            assert completed.dispatched_procedures == 2
            assert completed.procedure_failures == 0
            for procedure_run_id in procedure_run_ids:
                handle = lab.procedures.get(procedure_run_id)
                snapshot = handle.snapshot
                assert snapshot.state == "closed"
                assert snapshot.closure is not None
                assert snapshot.closure.status == "succeeded"
                attempts = handle.steps(limit=10).items
                assert {attempt.step_key for attempt in attempts} == {
                    "baseline",
                    "fit",
                    "candidate",
                    "verification",
                }
                assert all(attempt.state == "succeeded" for attempt in attempts)
                assert all(
                    not isinstance(attempt.output, ConfigPublishOutputRef)
                    and attempt.operation != "config_publish"
                    for attempt in attempts
                )

            active_after = lab.config.active()
            assert active_after.entry.id == active_before.entry.id
            assert active_after.entry.content_hash == active_before.entry.content_hash
            assert (
                active_after.activation.generation
                == active_before.activation.generation
            )

            fresh = worker.cycle()

            assert fresh.fresh_calibrations == 2
            assert fresh.ready_calibrations == 0
            assert fresh.admitted_calibrations == 0
            assert fresh.created_calibration_cohorts == 0
            assert fresh.dispatched_procedures == 0

            reactivated = lab.config.set_default(
                active_after.config,
                entry_id="same-content-reactivation",
                note="test registry-only calibration provenance change",
            )
            assert reactivated.entry.id != active_before.entry.id
            assert reactivated.entry.content_hash == active_before.entry.content_hash
            assert (
                reactivated.activation.generation
                == active_before.activation.generation + 1
            )

            same_content = worker.cycle()

            assert same_content.fresh_calibrations == 2
            assert same_content.ready_calibrations == 0
            assert same_content.admitted_calibrations == 0
            assert same_content.created_calibration_cohorts == 0
            assert same_content.dispatched_procedures == 0
            [reopened_summary] = lab.calibrations.list(
                fanout_scope=DRAG_BETA_CALIBRATION_FANOUT_SCOPE
            ).items
            assert reopened_summary == summary
            reopened_members = lab.calibrations.members(cohort.cohort_id)
            assert (
                tuple(member.procedure_run_id for member in reopened_members.items)
                == procedure_run_ids
            )
    finally:
        stop_project(project)

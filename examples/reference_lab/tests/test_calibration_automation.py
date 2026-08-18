from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from scopecat import Quantity
from scopecat.api.procedure_worker import ProjectProcedureWorkerLoop
from scopecat.automation import ConfigPublishOutputRef
from scopecat.config.registry.records import CalibrationCohortMergeRegistrySource
from scopecat.daemon.client import DaemonConflictError
from scopecat.project import load_project
from scopecat_server.lifecycle import start_project, stop_project

from reference_lab.application import create_application
from reference_lab.configuration import EXAMPLE_ROOT
from reference_lab.parameters import Q0_DRAG_BETA
from reference_lab.workflows.drag_beta_automatic_publication import (
    DRAG_BETA_PUBLICATION_POLICY_REF,
)
from reference_lab.workflows.drag_beta_freshness import (
    DRAG_BETA_CALIBRATION_FANOUT_SCOPE,
    drag_beta_semantic_freshness_inputs,
)
from reference_lab.workflows.drag_beta_publication import (
    DRAG_BETA_COMPOSITION_POLICY_REF,
    prepare_drag_beta_cohort_publication,
    publish_verified_drag_beta_cohort,
)


def test_resident_automatic_publication_survives_restart_and_q0_only(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "reference-lab-resident-calibration"
    shutil.copytree(EXAMPLE_ROOT / "config", project_root / "config")
    shutil.copytree(EXAMPLE_ROOT / "src", project_root / "src")
    shutil.copy2(EXAMPLE_ROOT / "scopecat.toml", project_root / "scopecat.toml")
    project = load_project(project_root / "scopecat.toml")

    first_record = start_project(project)
    try:
        with create_application(project_root).connect(first_record.base_url) as lab:
            active_before = lab.config.active()
            worker = ProjectProcedureWorkerLoop(
                lab.procedures,
                calibration_finalizer=lab.calibrations.publication_finalizer(),
                calibration_evaluator=lab.calibrations.evaluator(),
                worker_id="reference-lab-resident-before-restart",
                runnable_limit=2,
            )

            completed = worker.cycle()

            assert completed.ready_calibration_publications == 0
            assert completed.published_calibration_publications == 0
            assert completed.admitted_calibrations == 2
            assert completed.created_calibration_cohorts == 1
            assert completed.dispatched_procedures == 2
            [summary] = lab.calibrations.list(
                fanout_scope=DRAG_BETA_CALIBRATION_FANOUT_SCOPE
            ).items
            cohort = lab.calibrations.get(summary.cohort_id)
            assert cohort.spec.automatic_publication == (
                DRAG_BETA_PUBLICATION_POLICY_REF
            )
            member_page = lab.calibrations.members(cohort.cohort_id)
            assert tuple(member.spec.target.id for member in member_page.items) == (
                "q0",
                "q1",
            )
            ready = lab.calibrations.publication_finalization(cohort.cohort_id)
            assert ready.state == "ready"
            assert ready.policy == DRAG_BETA_PUBLICATION_POLICY_REF
            assert ready.base_config_source == cohort.spec.config_source
            assert lab.config.active().activation == active_before.activation

        stopped = stop_project(project)
        assert stopped.state == "running"
        restarted_record = start_project(project)

        with create_application(project_root).connect(restarted_record.base_url) as lab:
            worker = ProjectProcedureWorkerLoop(
                lab.procedures,
                calibration_finalizer=lab.calibrations.publication_finalizer(),
                calibration_evaluator=lab.calibrations.evaluator(),
                worker_id="reference-lab-resident-after-restart",
                runnable_limit=2,
            )

            published = worker.cycle()

            assert published.ready_calibration_publications == 1
            assert published.prepared_calibration_publications == 1
            assert published.published_calibration_publications == 1
            assert published.calibration_publication_failures == 0
            assert published.calibration_publication_barrier is False
            assert published.fresh_calibrations == 2
            assert published.pending_publication_calibrations == 0
            assert published.admitted_calibrations == 0
            assert published.created_calibration_cohorts == 0
            assert published.dispatched_procedures == 0

            active_published = lab.config.active()
            assert active_published.activation.generation == (
                active_before.activation.generation + 1
            )
            finalized = lab.calibrations.publication_finalization(cohort.cohort_id)
            assert finalized.state == "published"
            assert finalized.publication is not None
            assert isinstance(
                active_published.entry.source,
                CalibrationCohortMergeRegistrySource,
            )
            assert len(active_published.entry.source.contributions) == 2
            calibration_keys = tuple(
                member.spec.calibration_key for member in member_page.items
            )
            statuses = lab.calibrations.status(
                calibration_keys,
                fanout_scope=DRAG_BETA_CALIBRATION_FANOUT_SCOPE,
            )
            assert all(
                status.latest_success is not None
                and status.latest_success.publication is not None
                and status.latest_success.publication.operation_id
                == finalized.publication.operation_id
                for status in statuses.statuses
            )

            replay = worker.cycle()
            assert replay.ready_calibration_publications == 0
            assert replay.published_calibration_publications == 0
            assert replay.fresh_calibrations == 2
            assert replay.created_calibration_cohorts == 0
            assert lab.config.active().activation == active_published.activation

            q0_inputs = drag_beta_semantic_freshness_inputs(
                active_published.config,
                "q0",
            )
            external_q0 = lab.config.set_default(
                lab.config.edit(active_published.config).apply(
                    Q0_DRAG_BETA.update(
                        Quantity(q0_inputs.active_drag_beta_ns + 0.5, "ns")
                    )
                ),
                entry_id="resident-external-q0-drag-beta-drift",
                note="exercise resident owner-specific publication",
            )

            q0_completed = worker.cycle()

            assert q0_completed.ready_calibration_publications == 0
            assert q0_completed.published_calibration_publications == 0
            assert q0_completed.fresh_calibrations == 1
            assert q0_completed.ready_calibrations == 1
            assert q0_completed.admitted_calibrations == 1
            assert q0_completed.created_calibration_cohorts == 1
            assert q0_completed.dispatched_procedures == 1
            summaries = lab.calibrations.list(
                fanout_scope=DRAG_BETA_CALIBRATION_FANOUT_SCOPE
            ).items
            [q0_summary] = (
                item for item in summaries if item.cohort_id != cohort.cohort_id
            )
            q0_cohort = lab.calibrations.get(q0_summary.cohort_id)
            [q0_member] = lab.calibrations.members(q0_cohort.cohort_id).items
            assert q0_member.spec.target.id == "q0"
            assert (
                lab.calibrations.publication_finalization(q0_cohort.cohort_id).state
                == "ready"
            )

            q0_published = worker.cycle()

            assert q0_published.ready_calibration_publications == 1
            assert q0_published.prepared_calibration_publications == 1
            assert q0_published.published_calibration_publications == 1
            assert q0_published.calibration_publication_failures == 0
            assert q0_published.calibration_publication_barrier is False
            assert q0_published.fresh_calibrations == 2
            assert q0_published.pending_publication_calibrations == 0
            assert q0_published.admitted_calibrations == 0
            assert q0_published.created_calibration_cohorts == 0
            assert q0_published.dispatched_procedures == 0
            active_q0_published = lab.config.active()
            assert active_q0_published.activation.generation == (
                external_q0.activation.generation + 1
            )
            q0_finalized = lab.calibrations.publication_finalization(
                q0_cohort.cohort_id
            )
            assert q0_finalized.state == "published"
            assert q0_finalized.publication is not None
            assert isinstance(
                active_q0_published.entry.source,
                CalibrationCohortMergeRegistrySource,
            )
            assert len(active_q0_published.entry.source.contributions) == 1
            q0_statuses = {
                status.calibration_key: status
                for status in lab.calibrations.status(
                    calibration_keys,
                    fanout_scope=DRAG_BETA_CALIBRATION_FANOUT_SCOPE,
                ).statuses
            }
            q0_success = q0_statuses[q0_member.spec.calibration_key].latest_success
            assert q0_success is not None
            assert q0_success.publication is not None
            assert (
                q0_success.publication.operation_id
                == q0_finalized.publication.operation_id
            )
            [q1_member] = (
                member for member in member_page.items if member.spec.target.id == "q1"
            )
            q1_success = q0_statuses[q1_member.spec.calibration_key].latest_success
            assert q1_success is not None
            assert q1_success.publication is not None
            assert (
                q1_success.publication.operation_id
                == finalized.publication.operation_id
            )

            q0_replay = worker.cycle()
            assert q0_replay.ready_calibration_publications == 0
            assert q0_replay.published_calibration_publications == 0
            assert q0_replay.fresh_calibrations == 2
            assert q0_replay.created_calibration_cohorts == 0
            assert lab.config.active().activation == (active_q0_published.activation)
    finally:
        stop_project(project)


def test_calibration_cohort_survives_restart_and_publishes_once(
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
            with pytest.raises(ValueError, match="closed succeeded"):
                publish_verified_drag_beta_cohort(lab, cohort.cohort_id)
            still_active = lab.config.active()
            assert still_active.entry == active_before.entry
            assert still_active.activation == active_before.activation

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

            pending = worker.cycle()

            assert pending.fresh_calibrations == 0
            assert pending.pending_publication_calibrations == 2
            assert pending.ready_calibrations == 0
            assert pending.admitted_calibrations == 0
            assert pending.created_calibration_cohorts == 0
            assert pending.dispatched_procedures == 0

            same_base = worker.cycle()

            assert same_base.fresh_calibrations == 0
            assert same_base.pending_publication_calibrations == 2
            assert same_base.ready_calibrations == 0
            assert same_base.admitted_calibrations == 0
            assert same_base.created_calibration_cohorts == 0
            assert same_base.dispatched_procedures == 0

            prepared = prepare_drag_beta_cohort_publication(lab, cohort.cohort_id)
            assert prepared.base_config == active_before.config
            assert tuple(proposal.id for proposal in prepared.proposals) == (
                "q0-drag-beta",
                "q1-drag-beta",
            )
            assert tuple(
                contribution.member_id
                for contribution in prepared.plan.source.contributions
            ) == tuple(member.spec.member_id for member in member_page.items)
            assert (
                prepared.plan.source.composition_policy_ref
                == DRAG_BETA_COMPOSITION_POLICY_REF
            )
            assert prepared.plan.source.base_generation == (
                active_before.activation.generation
            )
            assert prepared.plan.source.expected_result_content_hash == (
                prepared.merge.content_hash
            )

            published = publish_verified_drag_beta_cohort(lab, cohort.cohort_id)

            assert published.operation.operation_id == prepared.plan.operation_id
            assert published.activation.generation == (
                active_before.activation.generation + 1
            )
            assert published.activation.previous_entry_id == active_before.entry.id
            assert published.entry.content_hash == prepared.merge.content_hash
            assert isinstance(
                published.entry.source,
                CalibrationCohortMergeRegistrySource,
            )
            assert published.entry.source.composition_policy_ref == (
                DRAG_BETA_COMPOSITION_POLICY_REF
            )
            assert len(published.entry.source.contributions) == 2
            assert len(published.calibration_successes) == 2
            assert all(
                success.publication is not None
                and success.publication.operation_id == published.operation.operation_id
                and success.publication.result_config_source.entry_id
                == published.entry.id
                and success.publication.result_config_source.registry_generation
                == published.activation.generation
                for success in published.calibration_successes
            )

            replayed = publish_verified_drag_beta_cohort(lab, cohort.cohort_id)
            assert replayed == published
            active_published = lab.config.active()
            assert active_published.activation.generation == (
                active_before.activation.generation + 1
            )
            assert active_published.entry == published.entry
            assert active_published.config == prepared.merge.config

            calibration_keys = tuple(
                member.spec.calibration_key for member in member_page.items
            )
            statuses = lab.calibrations.status(
                calibration_keys,
                fanout_scope=DRAG_BETA_CALIBRATION_FANOUT_SCOPE,
            )
            assert all(
                status.latest_success is not None
                and status.latest_success.publication is not None
                and status.latest_success.publication.operation_id
                == published.operation.operation_id
                for status in statuses.statuses
            )

            fresh = worker.cycle()
            assert fresh.fresh_calibrations == 2
            assert fresh.pending_publication_calibrations == 0
            assert fresh.ready_calibrations == 0
            assert fresh.admitted_calibrations == 0
            assert fresh.created_calibration_cohorts == 0
            assert fresh.dispatched_procedures == 0

            [reopened_summary] = lab.calibrations.list(
                fanout_scope=DRAG_BETA_CALIBRATION_FANOUT_SCOPE
            ).items
            assert reopened_summary == summary
            reopened_members = lab.calibrations.members(cohort.cohort_id)
            assert (
                tuple(member.procedure_run_id for member in reopened_members.items)
                == procedure_run_ids
            )

            q0_inputs = drag_beta_semantic_freshness_inputs(
                active_published.config,
                "q0",
            )
            external_q0 = lab.config.set_default(
                lab.config.edit(active_published.config).apply(
                    Q0_DRAG_BETA.update(
                        Quantity(q0_inputs.active_drag_beta_ns + 0.5, "ns")
                    )
                ),
                entry_id="external-q0-drag-beta-drift",
                note="exercise owner-specific published freshness",
            )
            assert external_q0.activation.generation == (
                published.activation.generation + 1
            )

            q0_due = worker.cycle()
            assert q0_due.selected_calibration_targets == 2
            assert q0_due.fresh_calibrations == 1
            assert q0_due.pending_publication_calibrations == 0
            assert q0_due.ready_calibrations == 1
            assert q0_due.admitted_calibrations == 1
            assert q0_due.created_calibration_cohorts == 1
            assert q0_due.dispatched_procedures == 1

            summaries = lab.calibrations.list(
                fanout_scope=DRAG_BETA_CALIBRATION_FANOUT_SCOPE
            ).items
            assert len(summaries) == 2
            [q0_summary] = (
                item for item in summaries if item.cohort_id != cohort.cohort_id
            )
            q0_cohort = lab.calibrations.get(q0_summary.cohort_id)
            q0_member_page = lab.calibrations.members(q0_cohort.cohort_id)
            [q0_member] = q0_member_page.items
            assert q0_member.spec.target.id == "q0"

            q0_pending = worker.cycle()
            assert q0_pending.fresh_calibrations == 1
            assert q0_pending.pending_publication_calibrations == 1
            assert q0_pending.ready_calibrations == 0
            assert q0_pending.admitted_calibrations == 0
            assert q0_pending.created_calibration_cohorts == 0
            assert q0_pending.dispatched_procedures == 0

            q0_prepared = prepare_drag_beta_cohort_publication(
                lab,
                q0_cohort.cohort_id,
            )
            assert tuple(proposal.id for proposal in q0_prepared.proposals) == (
                "q0-drag-beta",
            )
            assert len(q0_prepared.contributions) == 1

            q0_published = publish_verified_drag_beta_cohort(
                lab,
                q0_cohort.cohort_id,
            )
            assert q0_published.activation.generation == (
                external_q0.activation.generation + 1
            )
            assert len(q0_published.calibration_successes) == 1
            assert (
                q0_published.calibration_successes[0].attempt.member_id
                == q0_member.spec.member_id
            )
            assert (
                publish_verified_drag_beta_cohort(lab, q0_cohort.cohort_id)
                == q0_published
            )
            assert lab.config.active().activation.generation == (
                external_q0.activation.generation + 1
            )

            q0_fresh = worker.cycle()
            assert q0_fresh.fresh_calibrations == 2
            assert q0_fresh.pending_publication_calibrations == 0
            assert q0_fresh.ready_calibrations == 0
            assert q0_fresh.admitted_calibrations == 0
            assert q0_fresh.created_calibration_cohorts == 0
            assert q0_fresh.dispatched_procedures == 0
    finally:
        stop_project(project)


def test_verified_calibration_cohort_does_not_publish_after_base_drift(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "reference-lab-calibration-base-drift"
    shutil.copytree(EXAMPLE_ROOT / "config", project_root / "config")
    shutil.copytree(EXAMPLE_ROOT / "src", project_root / "src")
    shutil.copy2(EXAMPLE_ROOT / "scopecat.toml", project_root / "scopecat.toml")
    project = load_project(project_root / "scopecat.toml")

    record = start_project(project)
    try:
        with create_application(project_root).connect(record.base_url) as lab:
            base = lab.config.active()
            admitted = lab.calibrations.evaluator().cycle()
            assert admitted.created_cohorts == 1
            [summary] = lab.calibrations.list(
                fanout_scope=DRAG_BETA_CALIBRATION_FANOUT_SCOPE
            ).items
            cohort = lab.calibrations.get(summary.cohort_id)
            worker = ProjectProcedureWorkerLoop(
                lab.procedures,
                calibration_evaluator=lab.calibrations.evaluator(),
                worker_id="reference-lab-calibration-base-drift",
                runnable_limit=2,
            )
            completed = worker.cycle()
            assert completed.dispatched_procedures == 2
            pending = worker.cycle()
            assert pending.pending_publication_calibrations == 2
            prepared = prepare_drag_beta_cohort_publication(lab, cohort.cohort_id)

            drifted = lab.config.set_default(
                base.config,
                entry_id="same-content-base-drift",
                note="advance the exact publication base",
            )
            assert drifted.activation.generation == base.activation.generation + 1

            with pytest.raises(DaemonConflictError):
                publish_verified_drag_beta_cohort(lab, cohort.cohort_id)

            active_after = lab.config.active()
            assert active_after.entry == drifted.entry
            assert active_after.activation == drifted.activation
            assert active_after.activation.generation == (
                base.activation.generation + 1
            )
            assert all(
                not isinstance(entry.source, CalibrationCohortMergeRegistrySource)
                for entry in lab.config.registry().entries
            )
            assert prepared.plan.source.base_generation == base.activation.generation
    finally:
        stop_project(project)

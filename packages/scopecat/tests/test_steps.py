from __future__ import annotations

from pathlib import Path

from scopecat._steps import (
    StepArtifactStore,
    StepJobArtifact,
    persist_completed_step,
    persist_failed_step,
)
from scopecat._storage import ARTIFACTS_DIR
from scopecat.diagnostics import Diagnostic
from scopecat.models.artifact import ProcessingJob
from scopecat.runs import open_run_store
from tests.support.records import artifact_refs_by_id, assert_artifact_ref, read_model
from tests.support.steps import artifact_diagnostics, make_simulated_run


def test_persist_completed_step_updates_manifest_refs(tmp_path: Path) -> None:
    run_id = make_simulated_run(tmp_path)
    storage = open_run_store(tmp_path)
    manifest = storage.read_manifest(run_id)
    artifact_store = StepArtifactStore(
        root_dir=storage.ref_path(run_id, ARTIFACTS_DIR),
        ref_dir=ARTIFACTS_DIR,
        diagnostics=artifact_diagnostics(),
    )
    artifact_store.write_text(
        id="step-summary",
        kind="summary",
        filename="step-summary.md",
        content="# Step\n",
    )
    job = ProcessingJob(
        id="step",
        run_id=run_id,
        step="step",
        input_artifact_ids=[],
        output_artifact_ids=list(artifact_store.output_artifact_ids),
        status="completed",
    )

    persist_completed_step(
        storage=storage,
        manifest=manifest,
        run_id=run_id,
        job_ref="processing/step.job.json",
        job=job,
        artifacts=artifact_store.artifacts,
        job_artifact=StepJobArtifact(id="step-job", kind="processing_job"),
    )

    updated = storage.read_manifest(run_id)
    assert_artifact_ref(
        updated.artifact_refs,
        "step-summary",
        path="artifacts/step-summary.md",
    )
    assert_artifact_ref(
        updated.artifact_refs,
        "step-job",
        path="processing/step.job.json",
    )


def test_persist_failed_step_updates_manifest_refs_without_proposals(
    tmp_path: Path,
) -> None:
    run_id = make_simulated_run(tmp_path)
    storage = open_run_store(tmp_path)
    manifest = storage.read_manifest(run_id)
    artifact_store = StepArtifactStore(
        root_dir=storage.ref_path(run_id, ARTIFACTS_DIR),
        ref_dir=ARTIFACTS_DIR,
        diagnostics=artifact_diagnostics(),
    )
    artifact_store.write_text(
        id="failed-summary",
        kind="summary",
        filename="failed-summary.md",
        content="# Failed\n",
    )
    artifact_store.reserve_file(
        id="reserved-debug",
        kind="debug",
        filename="reserved-debug.txt",
    )
    job = ProcessingJob(
        id="failed-step",
        run_id=run_id,
        step="failed-step",
        input_artifact_ids=["raw-measurements"],
        output_artifact_ids=list(artifact_store.output_artifact_ids),
        status="planned",
        diagnostics=[
            Diagnostic(
                severity="error",
                code="failed_step",
                message="failed",
                path="step",
            )
        ],
    )

    persist_failed_step(
        storage=storage,
        manifest=manifest,
        run_id=run_id,
        job_ref="processing/failed-step.job.json",
        job=job,
        artifacts=artifact_store.artifacts,
        job_artifact=StepJobArtifact(id="failed-step-job", kind="processing_job"),
    )

    persisted_job = read_model(
        storage.ref_path(run_id, "processing/failed-step.job.json"),
        ProcessingJob,
    )
    updated = storage.read_manifest(run_id)
    artifact_refs = artifact_refs_by_id(updated.artifact_refs)
    assert persisted_job.status == "failed"
    assert_artifact_ref(
        updated.artifact_refs,
        "failed-summary",
        path="artifacts/failed-summary.md",
    )
    assert_artifact_ref(
        updated.artifact_refs,
        "failed-step-job",
        path="processing/failed-step.job.json",
    )
    assert "reserved-debug" not in artifact_refs

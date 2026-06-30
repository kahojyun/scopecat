"""Internal persistence helpers for step jobs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from scopecat._storage.local import LocalRunStore
from scopecat.models.artifact import Artifact
from scopecat.models.run import RunManifest
from scopecat.runs.access import upsert_artifacts

StepJobStatus = Literal["completed", "failed"]


@dataclass(frozen=True)
class StepJobArtifact:
    """Optional manifest artifact for a persisted step job record."""

    id: str
    kind: str
    media_type: str | None = "application/json"
    metadata: dict[str, Any] = field(default_factory=dict)


def persist_completed_step(
    *,
    storage: LocalRunStore,
    manifest: RunManifest,
    run_id: str,
    job_ref: str,
    job: BaseModel,
    artifacts: Iterable[Artifact],
    job_artifact: StepJobArtifact | None = None,
) -> None:
    """Persist a completed processing/evaluation job and manifest updates."""

    persist_step_job(
        storage=storage,
        manifest=manifest,
        run_id=run_id,
        job_ref=job_ref,
        job=job,
        status="completed",
        artifacts=artifacts,
        job_artifact=job_artifact,
    )


def persist_failed_step(
    *,
    storage: LocalRunStore,
    manifest: RunManifest,
    run_id: str,
    job_ref: str,
    job: BaseModel,
    artifacts: Iterable[Artifact],
    job_artifact: StepJobArtifact | None = None,
) -> None:
    """Persist a failed processing/evaluation job and manifest updates."""

    persist_step_job(
        storage=storage,
        manifest=manifest,
        run_id=run_id,
        job_ref=job_ref,
        job=job,
        status="failed",
        artifacts=artifacts,
        job_artifact=job_artifact,
    )


def persist_step_job(
    *,
    storage: LocalRunStore,
    manifest: RunManifest,
    run_id: str,
    job_ref: str,
    job: BaseModel,
    status: StepJobStatus,
    artifacts: Iterable[Artifact],
    job_artifact: StepJobArtifact | None = None,
) -> None:
    """Persist a processing/evaluation job and manifest updates."""

    artifact_refs = list(artifacts)
    job = job.model_copy(update={"status": status})
    storage.write_model(run_id, job_ref, job)
    if job_artifact is not None:
        artifact_refs.append(
            Artifact(
                id=job_artifact.id,
                kind=job_artifact.kind,
                path=job_ref,
                media_type=job_artifact.media_type,
                metadata=job_artifact.metadata,
            )
        )
    manifest.artifact_refs = upsert_artifacts(manifest.artifact_refs, artifact_refs)
    storage.write_manifest(manifest)

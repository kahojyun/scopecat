"""Run content access use cases."""

from __future__ import annotations

from scopecat.kernel.errors import CheckFailed, DataIntegrityError
from scopecat.kernel.problems import (
    ProblemPhase,
    StorageLocation,
    model_location,
    problem,
)
from scopecat.project_state import ProjectStateServices
from scopecat.records.artifact import RunContentEntry
from scopecat.records.run_request import RunRequest
from scopecat.runs.access import (
    read_artifact_bytes,
    read_artifact_json,
    read_artifact_text,
    read_dataset_bytes,
    read_record_json,
    require_artifact,
    require_dataset,
    require_record,
)
from scopecat.runs.data import (
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunDatasetBytesResult,
    RunMeasurementDatasetResult,
    RunRecordJsonResult,
)
from scopecat.runs.measurements import read_measurement_dataset
from scopecat.runs.refs import (
    RUN_REQUEST_REF,
)
from scopecat.runs.repository import RunRepository


def load_run_request(*, run_id: str, services: ProjectStateServices) -> RunRequest:
    """Load the operator intent accepted with a run."""

    storage = services.runs
    _require_run_ref(
        storage=storage,
        run_id=run_id,
        ref=RUN_REQUEST_REF,
        code="run.request_missing",
        label="accepted run request",
    )
    return storage.read_model(run_id, RUN_REQUEST_REF, RunRequest)


def _require_run_ref(
    *,
    storage: RunRepository,
    run_id: str,
    ref: str,
    code: str,
    label: str,
) -> None:
    storage.read_manifest(run_id)
    if storage.exists(run_id, ref):
        return
    raise DataIntegrityError(
        [
            problem(
                code,
                f"run is missing its {label}",
                phase=ProblemPhase.PERSISTENCE,
                location=StorageLocation(run_id=run_id, ref=ref),
            )
        ]
    )


def read_run_artifact_text(
    *,
    run_id: str,
    selector: str,
    services: ProjectStateServices,
    expected_kind: str | None = None,
) -> RunArtifactTextResult:
    storage = services.runs
    artifact = require_artifact(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind=expected_kind,
    )
    if not _artifact_supports_text(artifact):
        raise CheckFailed(
            [
                problem(
                    "run.artifact_media_type_unsupported",
                    "run artifact media type does not support text access",
                    phase=ProblemPhase.ANALYSIS,
                    location=model_location("run_manifest", "artifacts", selector),
                    details={"media_type": _artifact_media_label(artifact)},
                )
            ]
        )
    return RunArtifactTextResult(
        artifact=artifact,
        content=read_artifact_text(
            storage=storage,
            run_id=run_id,
            artifact=artifact,
        ),
    )


def read_run_artifact_json(
    *,
    run_id: str,
    selector: str,
    services: ProjectStateServices,
    expected_kind: str | None = None,
) -> RunArtifactJsonResult:
    storage = services.runs
    artifact = require_artifact(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind=expected_kind,
    )
    return RunArtifactJsonResult(
        artifact=artifact,
        content=dict(
            read_artifact_json(
                storage=storage,
                run_id=run_id,
                artifact=artifact,
            )
        ),
    )


def read_run_record_json(
    *,
    run_id: str,
    selector: str,
    services: ProjectStateServices,
    expected_kind: str | None = None,
) -> RunRecordJsonResult:
    storage = services.runs
    record = require_record(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind=expected_kind,
    )
    return RunRecordJsonResult(
        record=record,
        content=dict(
            read_record_json(
                storage=storage,
                run_id=run_id,
                record=record,
            )
        ),
    )


def read_run_artifact_bytes(
    *,
    run_id: str,
    selector: str,
    services: ProjectStateServices,
    expected_kind: str | None = None,
) -> RunArtifactBytesResult:
    storage = services.runs
    artifact = require_artifact(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind=expected_kind,
    )
    return RunArtifactBytesResult(
        artifact=artifact,
        content=read_artifact_bytes(
            storage=storage,
            run_id=run_id,
            artifact=artifact,
        ),
    )


def read_run_dataset_bytes(
    *,
    run_id: str,
    selector: str,
    services: ProjectStateServices,
    expected_kind: str | None = None,
) -> RunDatasetBytesResult:
    storage = services.runs
    dataset = require_dataset(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind=expected_kind,
    )
    return RunDatasetBytesResult(
        dataset=dataset,
        content=read_dataset_bytes(
            storage=storage,
            run_id=run_id,
            dataset=dataset,
        ),
    )


def read_run_measurement_dataset(
    *,
    run_id: str,
    services: ProjectStateServices,
    selector: str = "raw-measurements",
) -> RunMeasurementDatasetResult:
    storage = services.runs
    dataset_entry = require_dataset(
        manifest=storage.read_manifest(run_id),
        selector=selector,
        expected_kind="measurement_dataset",
    )
    dataset = read_measurement_dataset(
        storage=storage,
        run_id=run_id,
        dataset=dataset_entry,
    )
    return RunMeasurementDatasetResult(dataset_entry=dataset_entry, dataset=dataset)


def _artifact_supports_text(artifact: RunContentEntry) -> bool:
    media_type = artifact.media_type
    return media_type is not None and (
        media_type.startswith("text/")
        or media_type in {"application/json", "application/x-ndjson"}
    )


def _artifact_media_label(artifact: RunContentEntry) -> str:
    if artifact.media_type is None:
        return "unknown"
    return artifact.media_type

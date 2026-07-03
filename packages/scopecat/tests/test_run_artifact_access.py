from __future__ import annotations

from scopecat.models.artifact import Artifact
from scopecat.models.run import RunManifest
from scopecat.runs import (
    get_artifact_by_id,
    list_artifacts,
    list_artifacts_by_kind,
    list_artifacts_by_metadata,
    upsert_artifacts,
)


def test_manifest_artifact_helpers_query_by_id_kind_and_metadata() -> None:
    manifest = _manifest(
        [
            Artifact(
                id="raw-measurements",
                kind="measurement_dataset",
                path="artifacts/raw-measurements.jsonl",
                metadata={"dataset_role": "raw", "source_step": "instrument"},
            ),
            Artifact(
                id="analysis-review",
                kind="analysis",
                path="artifacts/analysis-review.json",
                metadata={"source_step": "manual", "source_artifact_ids": ["raw"]},
            ),
            Artifact(
                id="analysis-promoted",
                kind="analysis",
                path="artifacts/analysis-promoted.json",
                metadata={"source_step": "analysis-step"},
            ),
        ]
    )

    assert (
        get_artifact_by_id(manifest, "raw-measurements") == (manifest.artifact_refs[0])
    )
    assert get_artifact_by_id(manifest, "missing") is None
    assert [artifact.id for artifact in list_artifacts(manifest)] == [
        "raw-measurements",
        "analysis-review",
        "analysis-promoted",
    ]
    analysis_artifacts = list_artifacts_by_kind(manifest, "analysis")
    assert [artifact.id for artifact in analysis_artifacts] == [
        "analysis-review",
        "analysis-promoted",
    ]
    assert [
        artifact.id
        for artifact in list_artifacts_by_metadata(
            manifest,
            {"source_step": "manual"},
        )
    ] == ["analysis-review"]
    assert [
        artifact.id
        for artifact in list_artifacts(
            manifest,
            kind="analysis",
            metadata={"source_step": "analysis-step"},
        )
    ] == ["analysis-promoted"]


def test_upsert_artifacts_replaces_by_artifact_id() -> None:
    existing = [
        Artifact(id="summary", kind="summary", path="artifacts/old.md"),
        Artifact(id="raw", kind="measurement_dataset", path="artifacts/raw.jsonl"),
    ]
    updated = upsert_artifacts(
        existing,
        [
            Artifact(id="summary", kind="summary", path="artifacts/new.md"),
            Artifact(id="analysis", kind="analysis", path="artifacts/analysis.json"),
        ],
    )

    assert [(artifact.id, artifact.path) for artifact in updated] == [
        ("raw", "artifacts/raw.jsonl"),
        ("summary", "artifacts/new.md"),
        ("analysis", "artifacts/analysis.json"),
    ]


def _manifest(artifacts: list[Artifact]) -> RunManifest:
    return RunManifest(
        run_id="run_test",
        status="completed",
        config_profile_snapshot_ref="config-profile.snapshot.json",
        plan_snapshot_ref="plan.snapshot.json",
        artifact_refs=artifacts,
    )

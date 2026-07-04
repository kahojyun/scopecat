from __future__ import annotations

from scopecat.models.artifact import RunArtifactEntry, RunDatasetEntry, RunRecordEntry
from scopecat.models.run import RunManifest
from scopecat.runs import (
    get_artifact_by_id,
    get_dataset_by_id,
    get_record_by_id,
    list_artifacts,
    list_artifacts_by_metadata,
    list_datasets,
    list_payload_entries,
    list_records,
    upsert_artifacts,
    upsert_datasets,
    upsert_records,
)


def test_manifest_entry_helpers_query_by_id_kind_and_metadata() -> None:
    manifest = _manifest(
        artifacts=[
            RunArtifactEntry(
                id="summary",
                kind="summary",
                metadata={"source_step": "manual"},
            ),
        ],
        datasets=[
            RunDatasetEntry(
                id="raw-measurements",
                kind="measurement_dataset",
                role="raw",
            )
        ],
        records=[
            RunRecordEntry(
                id="analysis-review",
                kind="analysis",
            ),
            RunRecordEntry(
                id="analysis-promoted",
                kind="analysis",
            ),
        ],
    )

    assert get_artifact_by_id(manifest, "summary") == manifest.artifacts[0]
    assert get_dataset_by_id(manifest, "raw-measurements") == manifest.datasets[0]
    assert get_record_by_id(manifest, "analysis-review") == manifest.records[0]
    assert get_artifact_by_id(manifest, "missing") is None
    assert [artifact.id for artifact in list_artifacts(manifest)] == [
        "summary",
    ]
    assert [dataset.id for dataset in list_datasets(manifest)] == ["raw-measurements"]
    analysis_records = list_records(manifest, kind="analysis")
    assert [record.id for record in analysis_records] == [
        "analysis-review",
        "analysis-promoted",
    ]
    assert [
        artifact.id
        for artifact in list_artifacts_by_metadata(
            manifest,
            {"source_step": "manual"},
        )
    ] == ["summary"]
    assert [entry.id for entry in list_payload_entries(manifest)] == [
        "raw-measurements",
        "summary",
    ]


def test_upsert_artifacts_replaces_by_artifact_id() -> None:
    existing = [
        RunArtifactEntry(id="summary", kind="summary"),
        RunArtifactEntry(id="plot", kind="figure"),
    ]
    updated = upsert_artifacts(
        existing,
        [
            RunArtifactEntry(id="summary", kind="updated_summary"),
            RunArtifactEntry(id="notes", kind="notes"),
        ],
    )

    assert [(artifact.id, artifact.kind) for artifact in updated] == [
        ("plot", "figure"),
        ("summary", "updated_summary"),
        ("notes", "notes"),
    ]


def test_upsert_datasets_and_records_replace_by_id() -> None:
    datasets = upsert_datasets(
        [RunDatasetEntry(id="raw", kind="measurement_dataset")],
        [RunDatasetEntry(id="raw", kind="data_table")],
    )
    records = upsert_records(
        [RunRecordEntry(id="analysis", kind="analysis")],
        [RunRecordEntry(id="analysis", kind="parameter_change_set")],
    )

    assert [(dataset.id, dataset.kind) for dataset in datasets] == [
        ("raw", "data_table")
    ]
    assert [(record.id, record.kind) for record in records] == [
        ("analysis", "parameter_change_set")
    ]


def _manifest(
    *,
    artifacts: list[RunArtifactEntry],
    datasets: list[RunDatasetEntry],
    records: list[RunRecordEntry],
) -> RunManifest:
    return RunManifest(
        run_id="run_test",
        status="completed",
        records=records,
        datasets=datasets,
        artifacts=artifacts,
    )

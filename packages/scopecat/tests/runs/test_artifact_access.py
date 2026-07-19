from __future__ import annotations

from scopecat.records.artifact import RunContentEntry
from scopecat.records.run import RunManifest, RunOutcome
from scopecat.runs.access import (
    get_artifact_by_id,
    get_dataset_by_id,
    get_record_by_id,
    list_artifacts,
    list_artifacts_by_metadata,
    list_datasets,
    list_payload_entries,
    list_records,
    upsert_contents,
)


def _entry(**fields: object) -> RunContentEntry:
    return RunContentEntry.model_validate({"content_hash": "test-content", **fields})


def test_manifest_entry_helpers_query_by_id_kind_and_metadata() -> None:
    manifest = _manifest(
        artifacts=[
            _entry(
                role="artifact",
                id="summary",
                kind="summary",
                metadata={"source_step": "manual"},
            ),
        ],
        datasets=[
            _entry(
                role="dataset",
                id="raw-measurements",
                kind="measurement_dataset",
                dataset_role="raw",
            )
        ],
        records=[
            _entry(
                role="record",
                id="analysis-review",
                kind="analysis",
            ),
            _entry(
                role="record",
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


def test_upsert_contents_replaces_by_artifact_id() -> None:
    existing = [
        _entry(role="artifact", id="summary", kind="summary"),
        _entry(role="artifact", id="plot", kind="figure"),
    ]
    updated = upsert_contents(
        existing,
        [
            _entry(role="artifact", id="summary", kind="updated_summary"),
            _entry(role="artifact", id="notes", kind="notes"),
        ],
    )

    assert [(artifact.id, artifact.kind) for artifact in updated] == [
        ("plot", "figure"),
        ("summary", "updated_summary"),
        ("notes", "notes"),
    ]


def test_upsert_contents_and_records_replace_by_id() -> None:
    datasets = upsert_contents(
        [_entry(role="dataset", id="raw", kind="measurement_dataset")],
        [_entry(role="dataset", id="raw", kind="data_table")],
    )
    records = upsert_contents(
        [_entry(role="record", id="analysis", kind="analysis")],
        [_entry(role="record", id="analysis", kind="parameter_change_proposal")],
    )

    assert [(dataset.id, dataset.kind) for dataset in datasets] == [
        ("raw", "data_table")
    ]
    assert [(record.id, record.kind) for record in records] == [
        ("analysis", "parameter_change_proposal")
    ]


def _manifest(
    *,
    artifacts: list[RunContentEntry],
    datasets: list[RunContentEntry],
    records: list[RunContentEntry],
) -> RunManifest:
    return RunManifest(
        run_id="run_test",
        lifecycle="terminal",
        config_content_hash="sha256:" + "0" * 64,
        outcome=RunOutcome(
            run_id="run_test",
            result="succeeded",
            certainty="known",
            termination_reason="completed",
        ),
        contents=(*records, *datasets, *artifacts),
    )

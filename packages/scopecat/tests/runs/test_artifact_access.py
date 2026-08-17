from __future__ import annotations

from scopecat.kernel.run_outcome import RunOutcome
from scopecat.records.content import ContentEntry
from scopecat.records.run import RunManifest
from scopecat.runs.access import (
    list_payload_entries,
    list_records,
    upsert_contents,
)


def _entry(**fields: object) -> ContentEntry:
    return ContentEntry.model_validate({"content_hash": "test-content", **fields})


def test_manifest_entry_helpers_list_by_role_kind_and_metadata() -> None:
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

    assert [
        artifact.id for artifact in list_payload_entries(manifest, kind="summary")
    ] == [
        "summary",
    ]
    analysis_records = list_records(manifest, kind="analysis")
    assert [record.id for record in analysis_records] == [
        "analysis-review",
        "analysis-promoted",
    ]
    assert [
        entry.id
        for entry in list_payload_entries(
            manifest,
            metadata={"source_step": "manual"},
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
        [_entry(role="dataset", id="raw", kind="updated_measurement_dataset")],
    )
    records = upsert_contents(
        [_entry(role="record", id="analysis", kind="analysis")],
        [_entry(role="record", id="analysis", kind="parameter_change_proposal")],
    )

    assert [(dataset.id, dataset.kind) for dataset in datasets] == [
        ("raw", "updated_measurement_dataset")
    ]
    assert [(record.id, record.kind) for record in records] == [
        ("analysis", "parameter_change_proposal")
    ]


def _manifest(
    *,
    artifacts: list[ContentEntry],
    datasets: list[ContentEntry],
    records: list[ContentEntry],
) -> RunManifest:
    return RunManifest(
        run_id="run_test",
        config_content_hash="sha256:" + "0" * 64,
        outcome=RunOutcome(
            run_id="run_test",
            result="succeeded",
            certainty="known",
        ),
        contents=(*records, *datasets, *artifacts),
    )

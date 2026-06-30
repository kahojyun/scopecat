from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scopecat._storage.local import LocalRunLayout, LocalRunStore
from scopecat.errors import ValidationFailed
from scopecat.models.run import RunEvent, RunManifest


def test_local_run_layout_resolves_run_relative_refs(tmp_path) -> None:
    layout = LocalRunLayout.from_workspace(tmp_path)

    assert layout.ref_path("run-000001", "artifacts/result.json") == (
        tmp_path / "runs" / "run-000001" / "artifacts" / "result.json"
    )

    with pytest.raises(ValidationFailed) as relative_escape:
        layout.ref_path("run-000001", "../outside.json")
    assert relative_escape.value.diagnostics[0].code == "artifact_path_escape"

    with pytest.raises(ValidationFailed) as absolute_escape:
        layout.ref_path("run-000001", "/outside.json")
    assert absolute_escape.value.diagnostics[0].code == "artifact_path_escape"


def test_local_run_store_round_trips_model_text_and_jsonl(tmp_path) -> None:
    store = LocalRunStore(tmp_path)
    run_id = "run-000001"
    manifest = _manifest(run_id, datetime(2026, 1, 1, tzinfo=UTC))
    events = [
        RunEvent(event_type="started", message="Started."),
        RunEvent(event_type="completed", message="Completed."),
    ]

    store.write_manifest(manifest)
    store.write_text(run_id, "artifacts/summary.md", "# Summary")
    store.write_jsonl(run_id, "events.jsonl", events)

    assert store.read_manifest(run_id) == manifest
    assert store.read_text(run_id, "artifacts/summary.md") == "# Summary\n"
    assert store.read_jsonl(run_id, "events.jsonl", RunEvent) == events


def test_local_run_store_lists_runs_by_created_at(tmp_path) -> None:
    store = LocalRunStore(tmp_path)
    later = _manifest("run-000002", datetime(2026, 1, 2, tzinfo=UTC))
    earlier = _manifest("run-000001", datetime(2026, 1, 1, tzinfo=UTC))

    store.write_manifest(later)
    store.write_manifest(earlier)

    assert [manifest.run_id for manifest in store.list_runs()] == [
        "run-000001",
        "run-000002",
    ]


def test_local_run_store_writes_manifest_atomically(tmp_path) -> None:
    store = LocalRunStore(tmp_path)
    run_id = "run-000001"
    store.write_manifest(_manifest(run_id, datetime(2026, 1, 1, tzinfo=UTC)))

    updated = _manifest(run_id, datetime(2026, 1, 1, tzinfo=UTC)).model_copy(
        update={"status": "failed", "finalization_summary": "Failed."}
    )
    store.write_manifest(updated)

    assert store.read_manifest(run_id).status == "failed"
    assert not store.ref_path(run_id, "manifest.json.tmp").exists()


def _manifest(run_id: str, created_at: datetime) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        created_at=created_at,
        status="planned",
        runner_id="test.runner",
        dry_run=False,
        workspace_ref="workspace",
        device_ref="device",
        experiment_ref="experiment",
        config_profile_snapshot_ref="config-profile.snapshot.json",
        plan_snapshot_ref="plan.snapshot.json",
        events_ref="events.jsonl",
        finalization_summary="Planned.",
    )

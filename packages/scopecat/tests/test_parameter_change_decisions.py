from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from pydantic import ValidationError

from scopecat._storage.refs import record_content_ref
from scopecat.errors import DataIntegrityError
from scopecat.parameter_changes import (
    invalidate_parameter_change_proposal,
    list_parameter_change_decisions,
    load_parameter_change_proposal,
    review_parameter_change_proposal,
)
from scopecat.run_overview import build_run_overview
from scopecat.runs import open_run_store
from tests.support.config_registry import signal_run_with_parameter_change


def test_invalidate_parameter_change_records_decision_without_mutating_proposal(
    tmp_path: Path,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    before = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
    )

    record = invalidate_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
        reason="active config changed before review",
        invalidated_by="operator",
        invalidated_by_refs=["config-profile.snapshot.json"],
    )

    assert record.schema_version == "scopecat.parameter_change_decision_record.v3"
    assert record.proposal_id == "best-signal"
    assert record.decision == "invalidated"
    assert record.note == "active config changed before review"
    assert record.actor == "operator"
    assert record.related_refs == ("config-profile.snapshot.json",)
    assert (
        load_parameter_change_proposal(
            run_id=run_id,
            selector="best-signal",
            workspace=tmp_path,
        )
        == before
    )
    manifest = open_run_store(tmp_path).read_manifest(run_id)
    decision_record = next(
        record
        for record in manifest.records
        if record.kind == "parameter_change_decision_record"
    )
    assert decision_record.id.startswith("best-signal-decision-")
    assert decision_record.kind == "parameter_change_decision_record"


def test_parameter_change_decisions_append_invalidation_after_approval(
    tmp_path: Path,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    approval = review_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
        state="approved",
        reviewer="operator",
        note="manual approval",
    )
    invalidation = invalidate_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
        reason="active config changed after review",
        invalidated_by="operator",
    )

    decisions = list_parameter_change_decisions(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
    )
    assert decisions == [approval, invalidation]
    assert [decision.decision for decision in decisions] == [
        "approved",
        "invalidated",
    ]
    manifest = open_run_store(tmp_path).read_manifest(run_id)
    decision_records = [
        record
        for record in manifest.records
        if record.kind == "parameter_change_decision_record"
    ]
    assert len(decision_records) == 2
    assert decision_records[0].id != decision_records[1].id
    overview = build_run_overview(run_id=run_id, workspace=tmp_path)
    decision_info = overview.parameter_change_proposals[0].decision_info
    assert decision_info.decision == "invalidated"
    assert [event.decision for event in decision_info.history] == [
        "approved",
        "invalidated",
    ]


def test_parameter_change_decision_history_fails_closed_on_corruption(
    tmp_path: Path,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    review_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
        state="approved",
        reviewer="operator",
    )
    storage = open_run_store(tmp_path)
    entry = next(
        record
        for record in storage.read_manifest(run_id).records
        if record.kind == "parameter_change_decision_record"
    )
    path = storage.ref_path(
        run_id,
        record_content_ref(record_id=entry.id, kind=entry.kind),
    )
    payload = json.loads(path.read_text())
    payload["run_id"] = "different-run"
    path.write_text(json.dumps(payload))

    with pytest.raises(DataIntegrityError) as error:
        list_parameter_change_decisions(
            run_id=run_id,
            selector="best-signal",
            workspace=tmp_path,
        )

    assert error.value.problems[0].code == (
        "invalid_parameter_change_decision_identity"
    )


def test_concurrent_parameter_decisions_preserve_every_append(
    tmp_path: Path,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    barrier = Barrier(2)

    def approve(actor: str) -> str:
        barrier.wait()
        return review_parameter_change_proposal(
            run_id=run_id,
            selector="best-signal",
            workspace=tmp_path,
            state="approved",
            reviewer=actor,
        ).event_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        event_ids = set(executor.map(approve, ("reviewer-a", "reviewer-b")))

    decisions = list_parameter_change_decisions(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
    )
    manifest = open_run_store(tmp_path).read_manifest(run_id)
    manifest_event_ids = {
        record.id.removeprefix("best-signal-decision-")
        for record in manifest.records
        if record.kind == "parameter_change_decision_record"
    }
    assert {decision.event_id for decision in decisions} == event_ids
    assert manifest_event_ids == event_ids
    assert not list((tmp_path / "runs" / run_id).rglob("*.tmp"))


def test_parameter_decision_copy_revalidates_identity(tmp_path: Path) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    decision = review_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
        state="approved",
        reviewer="reviewer",
    )

    with pytest.raises(ValidationError):
        decision.model_copy(update={"actor": ""})

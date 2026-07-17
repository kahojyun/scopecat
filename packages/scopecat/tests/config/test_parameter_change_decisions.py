from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from pydantic import ValidationError

from scopecat.composition.local import local_run_repository, local_workspace_services
from scopecat.config.changes import (
    invalidate_parameter_change_proposal,
    list_parameter_change_decisions,
    load_parameter_change_proposal,
    review_parameter_change_proposal,
)
from scopecat.kernel.errors import DataIntegrityError
from scopecat.runs.refs import record_content_ref
from tests.testkit.config_registry import signal_run_with_parameter_change


def test_invalidate_parameter_change_records_decision_without_mutating_proposal(
    tmp_path: Path,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    before = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=local_workspace_services(tmp_path),
    )

    record = invalidate_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=local_workspace_services(tmp_path),
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
            services=local_workspace_services(tmp_path),
        )
        == before
    )
    manifest = local_run_repository(tmp_path).read_manifest(run_id)
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
        services=local_workspace_services(tmp_path),
        state="approved",
        reviewer="operator",
        note="manual approval",
    )
    invalidation = invalidate_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=local_workspace_services(tmp_path),
        reason="active config changed after review",
        invalidated_by="operator",
    )

    decisions = list_parameter_change_decisions(
        run_id=run_id,
        selector="best-signal",
        storage=local_run_repository(tmp_path),
    )
    assert decisions == [approval, invalidation]
    assert [decision.decision for decision in decisions] == [
        "approved",
        "invalidated",
    ]
    manifest = local_run_repository(tmp_path).read_manifest(run_id)
    decision_records = [
        record
        for record in manifest.records
        if record.kind == "parameter_change_decision_record"
    ]
    assert len(decision_records) == 2
    assert decision_records[0].id != decision_records[1].id
    assert decisions[-1].decision == "invalidated"
    assert [event.decision for event in decisions] == [
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
        services=local_workspace_services(tmp_path),
        state="approved",
        reviewer="operator",
    )
    storage = local_run_repository(tmp_path)
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
            storage=storage,
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
            services=local_workspace_services(tmp_path),
            state="approved",
            reviewer=actor,
        ).event_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        event_ids = set(executor.map(approve, ("reviewer-a", "reviewer-b")))

    decisions = list_parameter_change_decisions(
        run_id=run_id,
        selector="best-signal",
        storage=local_run_repository(tmp_path),
    )
    manifest = local_run_repository(tmp_path).read_manifest(run_id)
    manifest_event_ids = {
        record.id.removeprefix("best-signal-decision-")
        for record in manifest.records
        if record.kind == "parameter_change_decision_record"
    }
    assert {decision.event_id for decision in decisions} == event_ids
    assert manifest_event_ids == event_ids
    assert not list((tmp_path / "runs" / run_id).rglob("*.tmp"))


def test_parameter_decision_validation_rejects_empty_actor(tmp_path: Path) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    decision = review_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=local_workspace_services(tmp_path),
        state="approved",
        reviewer="reviewer",
    )

    invalid = decision.model_dump(mode="python")
    invalid["actor"] = ""
    with pytest.raises(ValidationError):
        type(decision).model_validate(invalid)

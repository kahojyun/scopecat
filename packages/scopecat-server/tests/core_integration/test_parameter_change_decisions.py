from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from scopecat.config.changes import (
    list_parameter_change_proposals,
    load_parameter_change_approval,
    load_parameter_change_proposal,
    prepare_parameter_change_proposal_contents,
)
from scopecat.kernel.errors import Conflict, DataIntegrityError
from scopecat.records.parameter_change import ParameterChangeApprovalRecord
from scopecat.runs.refs import record_content_ref
from scopecat.runs.repository import RunContentPublication
from scopecat_testkit.config_registry import review_parameter_change_proposal
from scopecat_testkit.server.config_registry import signal_run_with_parameter_change
from scopecat_testkit.server.runtime import (
    sqlite_project_services,
    sqlite_run_repository,
)


def test_same_proposal_intent_retry_reuses_durable_entry_hash(
    tmp_path: Path,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    services = sqlite_project_services(tmp_path)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=services,
    )
    durable_entry = services.runs.read_content(
        run_id,
        role="record",
        content_id=proposal.id,
    )

    prepared = prepare_parameter_change_proposal_contents(
        storage=services.runs,
        run_id=run_id,
        proposals=(
            proposal.model_copy(
                update={"proposed_at": proposal.proposed_at + timedelta(seconds=1)}
            ),
        ),
    )

    assert prepared.entries == (durable_entry,)
    assert prepared.writes == ()
    with pytest.raises(Conflict):
        prepare_parameter_change_proposal_contents(
            storage=services.runs,
            run_id=run_id,
            proposals=(
                proposal.model_copy(update={"reason": "different scientific intent"}),
            ),
        )


def test_parameter_change_approval_is_single_and_idempotent(tmp_path: Path) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    services = sqlite_project_services(tmp_path)
    first = review_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=services,
        reviewer="reviewer-a",
        note="evidence reviewed",
    )
    second = review_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=services,
        reviewer="reviewer-a",
        note="evidence reviewed",
    )

    assert second == first
    with pytest.raises(Conflict):
        review_parameter_change_proposal(
            run_id=run_id,
            selector="best-signal",
            services=services,
            reviewer="reviewer-b",
            note="evidence reviewed",
        )
    with pytest.raises(Conflict):
        review_parameter_change_proposal(
            run_id=run_id,
            selector="best-signal",
            services=services,
            reviewer="reviewer-a",
            note="different evidence",
        )
    assert (
        load_parameter_change_approval(
            run_id=run_id,
            selector="best-signal",
            storage=services.runs,
        )
        == first
    )
    records = services.runs.list_contents(
        run_id,
        limit=100,
        role="record",
        kind="parameter_change_approval_record",
    ).items
    assert [entry.id for entry in records] == ["best-signal-approval"]


def test_exact_proposal_and_approval_reads_do_not_scan_content_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    services = sqlite_project_services(tmp_path)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=services,
    )
    approval = review_parameter_change_proposal(
        run_id=run_id,
        selector=proposal.id,
        services=services,
        reviewer="operator",
    )

    def fail_scan(*_args: object, **_kwargs: object) -> None:
        pytest.fail("exact proposal reads must not scan content pages")

    monkeypatch.setattr(services.runs, "list_contents", fail_scan)

    assert (
        load_parameter_change_proposal(
            run_id=run_id,
            selector=proposal.id,
            services=services,
        )
        == proposal
    )
    assert (
        load_parameter_change_approval(
            run_id=run_id,
            selector=proposal.id,
            storage=services.runs,
        )
        == approval
    )


def test_parameter_change_proposals_are_paged_newest_first(tmp_path: Path) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    services = sqlite_project_services(tmp_path)
    first = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=services,
    )
    second = first.model_copy(update={"id": "second-signal"})
    prepared = prepare_parameter_change_proposal_contents(
        storage=services.runs,
        run_id=run_id,
        proposals=(second,),
    )
    services.runs.publish_content(
        RunContentPublication(
            run_id=run_id,
            entries=prepared.entries,
            models=prepared.writes,
        )
    )

    latest = list_parameter_change_proposals(
        run_id=run_id,
        services=services,
        limit=1,
    )
    assert latest.items == (second,)
    assert latest.next_cursor is not None
    older = list_parameter_change_proposals(
        run_id=run_id,
        services=services,
        limit=1,
        before=latest.next_cursor,
    )
    assert older.items == (first,)
    assert older.next_cursor is None


def test_parameter_change_approval_fails_closed_on_corruption(
    tmp_path: Path,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    review_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=sqlite_project_services(tmp_path),
        reviewer="operator",
    )
    storage = sqlite_run_repository(tmp_path)
    [entry] = storage.list_contents(
        run_id,
        limit=100,
        role="record",
        kind="parameter_change_approval_record",
    ).items
    ref = record_content_ref(record_id=entry.id, kind=entry.kind)
    payload = json.loads(storage.read_text(run_id, ref))
    payload["run_id"] = "different-run"
    storage.write_text(run_id, ref, json.dumps(payload))

    with pytest.raises(DataIntegrityError) as error:
        load_parameter_change_approval(
            run_id=run_id,
            selector="best-signal",
            storage=storage,
        )

    assert error.value.problems[0].code == (
        "invalid_parameter_change_approval_identity"
    )


def test_parameter_approval_validation_rejects_empty_actor() -> None:
    with pytest.raises(ValidationError):
        ParameterChangeApprovalRecord(
            run_id="run-1",
            proposal_id="proposal-1",
            actor="",
        )

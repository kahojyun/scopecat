from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from testkit.config_registry import (
    review_parameter_change_proposal,
    signal_run_with_parameter_change,
)
from testkit.runtime import sqlite_project_services, sqlite_run_repository

from scopecat.config.changes import (
    load_parameter_change_approval,
    load_parameter_change_proposal,
    prepare_parameter_change_proposal_contents,
)
from scopecat.kernel.errors import Conflict, DataIntegrityError
from scopecat.records.parameter_change import ParameterChangeApprovalRecord
from scopecat.runs.refs import record_content_ref


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
    durable_entry = next(
        entry
        for entry in services.runs.read_manifest(run_id).records
        if entry.id == proposal.id
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
    records = [
        entry
        for entry in services.runs.read_manifest(run_id).records
        if entry.kind == "parameter_change_approval_record"
    ]
    assert [entry.id for entry in records] == ["best-signal-approval"]


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
    entry = next(
        record
        for record in storage.read_manifest(run_id).records
        if record.kind == "parameter_change_approval_record"
    )
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

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from scopecat.config.changes import (
    list_parameter_change_decisions,
    load_parameter_change_proposal,
    prepare_parameter_change_proposal_contents,
)
from scopecat.kernel.errors import Conflict, DataIntegrityError
from scopecat.records.parameter_change import AutomaticPolicyDecisionAuthority
from scopecat.runs.refs import record_content_ref
from tests.testkit.config_registry import (
    decide_parameter_change_proposal,
    review_parameter_change_proposal,
    signal_run_with_parameter_change,
)
from tests.testkit.runtime import (
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


def test_automatic_policy_decision_authority_round_trips_without_verification(
    tmp_path: Path,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    authority = AutomaticPolicyDecisionAuthority(
        actor="nightly-calibration",
        policy_id="high-confidence-fit",
        policy_version="3",
    )

    decision = decide_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=sqlite_project_services(tmp_path),
        decision="approved",
        authority=authority,
        note="fit confidence exceeded the automatic acceptance threshold",
    )

    assert list_parameter_change_decisions(
        run_id=run_id,
        selector="best-signal",
        storage=sqlite_run_repository(tmp_path),
    ) == [decision]
    assert decision.authority == authority


def test_parameter_change_decision_history_fails_closed_on_corruption(
    tmp_path: Path,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    review_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=sqlite_project_services(tmp_path),
        state="approved",
        reviewer="operator",
    )
    storage = sqlite_run_repository(tmp_path)
    entry = next(
        record
        for record in storage.read_manifest(run_id).records
        if record.kind == "parameter_change_decision_record"
    )
    ref = record_content_ref(record_id=entry.id, kind=entry.kind)
    payload = json.loads(storage.read_text(run_id, ref))
    payload["run_id"] = "different-run"
    storage.write_text(run_id, ref, json.dumps(payload))

    with pytest.raises(DataIntegrityError) as error:
        list_parameter_change_decisions(
            run_id=run_id,
            selector="best-signal",
            storage=storage,
        )

    assert error.value.problems[0].code == (
        "invalid_parameter_change_decision_identity"
    )


def test_parameter_decisions_preserve_every_append(tmp_path: Path) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    event_ids = {
        review_parameter_change_proposal(
            run_id=run_id,
            selector="best-signal",
            services=sqlite_project_services(tmp_path),
            state="approved",
            reviewer=actor,
        ).event_id
        for actor in ("reviewer-a", "reviewer-b")
    }

    decisions = list_parameter_change_decisions(
        run_id=run_id,
        selector="best-signal",
        storage=sqlite_run_repository(tmp_path),
    )
    manifest = sqlite_run_repository(tmp_path).read_manifest(run_id)
    manifest_event_ids = {
        record.id.removeprefix("best-signal-decision-")
        for record in manifest.records
        if record.kind == "parameter_change_decision_record"
    }
    assert {decision.event_id for decision in decisions} == event_ids
    assert manifest_event_ids == event_ids


def test_parameter_decision_validation_rejects_empty_actor(tmp_path: Path) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    decision = review_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=sqlite_project_services(tmp_path),
        state="approved",
        reviewer="reviewer",
    )

    invalid = decision.model_dump(mode="python")
    invalid["authority"]["actor"] = ""
    with pytest.raises(ValidationError):
        type(decision).model_validate(invalid)

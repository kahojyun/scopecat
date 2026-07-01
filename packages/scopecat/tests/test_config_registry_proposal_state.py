from __future__ import annotations

import json
from pathlib import Path

import pytest

from scopecat.config_registry import list_config_registry_entries
from scopecat.errors import ValidationFailed
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.proposals import (
    accept_parameter_proposal,
    invalidate_parameter_proposal,
    load_parameter_proposal,
    review_parameter_proposal,
)
from scopecat.runs import open_run_store
from tests.support.config_registry import simulate_with_proposal
from tests.support.records import assert_artifact_ref, read_model


def test_invalidate_parameter_proposal_records_boundary_and_manifest(
    tmp_path: Path,
) -> None:
    run_id = simulate_with_proposal(tmp_path)

    invalidated, record = invalidate_parameter_proposal(
        run_id=run_id,
        selector="best-signal-proposal",
        workspace=tmp_path,
        reason="active config changed before review",
        invalidated_by="operator",
        invalidated_by_refs=["config-profile.snapshot.json"],
    )

    assert invalidated.state == "invalidated"
    assert record.schema_version == "scopecat.proposal_invalidation_record.v1"
    assert record.proposal_id == "best-signal-proposal"
    assert record.proposal_artifact_id == "best-signal-proposal"
    assert record.reason == "active config changed before review"
    assert record.invalidated_by == "operator"
    assert record.invalidated_by_refs == ["config-profile.snapshot.json"]

    stored_proposal = load_parameter_proposal(
        run_id=run_id,
        selector="best-signal-proposal",
        workspace=tmp_path,
    )
    assert stored_proposal == invalidated
    assert not (
        tmp_path / "runs" / run_id / "reviews" / "best-signal-proposal.review.json"
    ).exists()
    assert not (
        tmp_path
        / "runs"
        / run_id
        / "reviews"
        / "best-signal-proposal.finalization.json"
    ).exists()

    manifest = open_run_store(tmp_path).read_manifest(run_id)
    assert_artifact_ref(
        manifest.artifact_refs,
        "best-signal-proposal-invalidation",
        kind="proposal_invalidation_record",
    )

    with pytest.raises(ValidationFailed) as error:
        accept_parameter_proposal(
            run_id=run_id,
            selector="best-signal-proposal",
            workspace=tmp_path,
            reviewer="operator",
            operator="operator",
        )

    assert error.value.diagnostics[0].code == "proposal_not_acceptable"


def test_invalidate_parameter_proposal_rejects_final_review_state(
    tmp_path: Path,
) -> None:
    run_id = simulate_with_proposal(tmp_path)
    review_parameter_proposal(
        run_id=run_id,
        selector="best-signal-proposal",
        workspace=tmp_path,
        state="approved",
        reviewer="operator",
        note="manual approval",
    )

    with pytest.raises(ValidationFailed) as error:
        invalidate_parameter_proposal(
            run_id=run_id,
            selector="best-signal-proposal",
            workspace=tmp_path,
            reason="active config changed after review",
            invalidated_by="operator",
        )

    assert error.value.diagnostics[0].code == "proposal_not_invalidatable"
    assert not (
        tmp_path
        / "runs"
        / run_id
        / "reviews"
        / "best-signal-proposal.invalidation.json"
    ).exists()


def test_accept_parameter_proposal_preflight_failure_does_not_review(
    tmp_path: Path,
) -> None:
    run_id = simulate_with_proposal(tmp_path)
    config_path = tmp_path / "runs" / run_id / "config-profile.snapshot.json"
    persisted_config = read_model(config_path, ConfigProfileSnapshot)
    config = persisted_config.model_dump(mode="json")
    config["parameter_state"]["scalar_values"]["values"] = []
    config_path.write_text(json.dumps(config, indent=2) + "\n")

    with pytest.raises(ValidationFailed) as error:
        accept_parameter_proposal(
            run_id=run_id,
            selector="best-signal-proposal",
            workspace=tmp_path,
            reviewer="operator",
            operator="operator",
        )

    assert error.value.diagnostics[0].code == "proposal_acceptance_patch_invalid"
    proposal = load_parameter_proposal(
        run_id=run_id,
        selector="best-signal-proposal",
        workspace=tmp_path,
    )
    assert proposal.state == "proposed"
    assert not (tmp_path / "runs" / run_id / "reviews").exists()
    assert list_config_registry_entries(workspace=tmp_path) == []

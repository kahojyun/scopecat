from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.errors import ValidationFailed
from scopecat.parameter_changes import (
    invalidate_parameter_change,
    load_parameter_change,
    review_parameter_changes,
)
from scopecat.runs import open_run_store
from tests.support.config_registry import signal_run_with_parameter_change
from tests.support.records import assert_artifact_ref


def test_invalidate_parameter_change_records_decision_without_mutating_change_set(
    tmp_path: Path,
) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    before = load_parameter_change(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
    )

    record = invalidate_parameter_change(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
        reason="active config changed before review",
        invalidated_by="operator",
        invalidated_by_refs=["config-profile.snapshot.json"],
    )

    assert record.schema_version == "scopecat.parameter_change_decision_record.v1"
    assert record.change_set_id == "best-signal"
    assert record.change_set_artifact_id == "best-signal"
    assert record.decision == "invalidated"
    assert record.note == "active config changed before review"
    assert record.actor == "operator"
    assert record.related_refs == ["config-profile.snapshot.json"]
    assert (
        load_parameter_change(
            run_id=run_id,
            selector="best-signal",
            workspace=tmp_path,
        )
        == before
    )
    assert (
        tmp_path
        / "runs"
        / run_id
        / "reviews"
        / "best-signal.parameter-change-decision.json"
    ).is_file()

    manifest = open_run_store(tmp_path).read_manifest(run_id)
    assert_artifact_ref(
        manifest.artifact_refs,
        "best-signal-decision",
        kind="parameter_change_decision_record",
    )


def test_parameter_change_decision_rejects_second_decision(tmp_path: Path) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    review_parameter_changes(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
        state="approved",
        reviewer="operator",
        note="manual approval",
    )

    with pytest.raises(ValidationFailed) as error:
        invalidate_parameter_change(
            run_id=run_id,
            selector="best-signal",
            workspace=tmp_path,
            reason="active config changed after review",
            invalidated_by="operator",
        )

    assert error.value.diagnostics[0].code == "parameter_change_decision_exists"

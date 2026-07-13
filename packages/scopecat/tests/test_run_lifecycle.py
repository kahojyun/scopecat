from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from scopecat._execution.evidence import (
    build_execution_manifest,
    execution_summary_ref,
    instrument_state_evidence_ref,
    run_outcome_ref,
)
from scopecat._execution.run_lifecycle import commit_terminal_evidence
from scopecat._storage.local import LocalRunStore
from scopecat.models.execution import ExecutionSummary
from scopecat.models.run import RunOutcome
from scopecat.models.run_plan import RunPlanOutput, RunPlanProducerKind


def _successful_outcome(run_id: str) -> RunOutcome:
    return RunOutcome(
        run_id=run_id,
        result="succeeded",
        certainty="known",
        termination_reason="completed",
    )


def _empty_summary(run_id: str, outcome: RunOutcome) -> ExecutionSummary:
    return ExecutionSummary(
        run_id=run_id,
        experiment_id="experiment",
        outcome=outcome,
        point_count=0,
        completed_point_count=0,
        measurement_count=0,
        instrument_ids=[],
        problem_count=0,
    )


def test_terminal_evidence_can_omit_instrument_state(tmp_path: Path) -> None:
    run_id = "run-domain"
    outcome = _successful_outcome(run_id)
    manifest = build_execution_manifest(
        run_id=run_id,
        outcome=outcome,
        measurements=[],
        expected_schema=None,
        config_source=None,
        include_instrument_state=False,
    )
    storage = LocalRunStore(tmp_path)

    commit_terminal_evidence(
        storage=storage,
        run_id=run_id,
        outcome=outcome,
        summary=_empty_summary(run_id, outcome),
        instrument_state=None,
        measurements=(),
        manifest=manifest,
    )

    assert {record.id for record in manifest.records} == {
        "execution-summary",
        "run-outcome",
    }
    assert storage.exists(run_id, run_outcome_ref())
    assert storage.exists(run_id, execution_summary_ref())
    assert not storage.exists(run_id, instrument_state_evidence_ref())
    assert storage.read_manifest(run_id) == manifest


def test_execution_manifest_includes_instrument_state_by_default() -> None:
    outcome = _successful_outcome("run-instrument")

    manifest = build_execution_manifest(
        run_id=outcome.run_id,
        outcome=outcome,
        measurements=[],
        expected_schema=None,
        config_source=None,
    )

    assert "instrument-state-evidence" in {record.id for record in manifest.records}


@pytest.mark.parametrize(
    "producer_kind",
    ["instrument", "domain", "host_transform"],
)
def test_run_plan_output_accepts_execution_producer_kinds(
    producer_kind: str,
) -> None:
    output = RunPlanOutput(
        id="signal",
        kind="observable",
        producer_kind=cast("RunPlanProducerKind", producer_kind),
        producer_unit_id="producer-unit",
        dtype="float64",
    )

    assert output.producer_kind == producer_kind


def test_run_plan_output_rejects_unknown_producer_kind() -> None:
    with pytest.raises(ValidationError, match="producer_kind"):
        RunPlanOutput.model_validate(
            {
                "id": "signal",
                "kind": "observable",
                "producer_kind": "compute",
                "producer_unit_id": "producer-unit",
                "dtype": "float64",
            }
        )

"""Shared durable run-lifecycle persistence."""

from __future__ import annotations

from collections.abc import Sequence

from scopecat._execution.evidence import (
    execution_summary_ref,
    instrument_state_evidence_ref,
    raw_measurements_ref,
    run_outcome_ref,
)
from scopecat._execution.problems import (
    contextualize_problems,
    problem_from_exception,
)
from scopecat._measurement_storage import write_measurement_records_path
from scopecat._storage.local import LocalRunStore
from scopecat._storage.refs import MANIFEST_REF
from scopecat.errors import ProblemFailure, RunPersistenceError
from scopecat.models.execution import ExecutionSummary, InstrumentStateEvidence
from scopecat.models.run import RunManifest, RunOutcome
from scopecat.problems import ProblemCategory, ProblemPhase
from scopecat.results import MeasurementRecord


def commit_terminal_evidence(
    *,
    storage: LocalRunStore,
    run_id: str,
    outcome: RunOutcome,
    summary: ExecutionSummary,
    instrument_state: InstrumentStateEvidence | None,
    measurements: Sequence[MeasurementRecord],
    manifest: RunManifest,
) -> None:
    """Commit terminal content before publishing the terminal manifest marker.

    Instrument-backed execution supplies state evidence. Other execution domains
    omit it instead of publishing an empty record that claims instrument state was
    observed.
    """

    committed_refs: list[str] = []
    phase = "run_outcome"
    pending_ref = run_outcome_ref()
    try:
        storage.write_model_atomic(run_id, pending_ref, outcome)
        committed_refs.append(pending_ref)
        phase = "execution_summary"
        pending_ref = execution_summary_ref()
        storage.write_model_atomic(run_id, pending_ref, summary)
        committed_refs.append(pending_ref)
        if instrument_state is not None:
            phase = "instrument_state_evidence"
            pending_ref = instrument_state_evidence_ref()
            storage.write_model_atomic(
                run_id,
                pending_ref,
                instrument_state,
            )
            committed_refs.append(pending_ref)
        if measurements:
            phase = "measurement_dataset"
            pending_ref = raw_measurements_ref()
            write_measurement_records_path(
                path=storage.ref_path(run_id, pending_ref),
                records=measurements,
            )
            committed_refs.append(pending_ref)
        phase = "terminal_manifest"
        pending_ref = MANIFEST_REF
        storage.write_manifest(manifest)
        committed_refs.append(pending_ref)
    except ProblemFailure as error:
        problems = contextualize_problems(
            error.problems,
            run_id=run_id,
            operation_id=f"terminalize.{phase}",
        )
        raise RunPersistenceError(
            problems,
            run_id=run_id,
            phase=phase,
            reconciliation="inspect_run_execution before retrying terminalization",
            retry="after_reconciliation",
            certainty=outcome.certainty,
            committed_refs=committed_refs,
            pending_ref=pending_ref,
        ) from error
    except Exception as error:
        problem = problem_from_exception(
            "run_terminal_persistence_failed",
            f"terminal run evidence could not be committed during {phase}",
            run_id=run_id,
            operation_id=f"terminalize.{phase}",
            error=error,
            phase=ProblemPhase.PERSISTENCE,
            category=ProblemCategory.STORAGE,
        )
        raise RunPersistenceError(
            (problem,),
            run_id=run_id,
            phase=phase,
            reconciliation="inspect_run_execution before retrying terminalization",
            retry="after_reconciliation",
            certainty=outcome.certainty,
            committed_refs=committed_refs,
            pending_ref=pending_ref,
        ) from error


__all__ = ["commit_terminal_evidence"]

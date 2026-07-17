"""Shared durable run-lifecycle persistence."""

from __future__ import annotations

from collections.abc import Sequence

from scopecat.execution.evidence import (
    instrument_state_evidence_ref,
    raw_measurements_ref,
    run_outcome_ref,
)
from scopecat.execution.problems import (
    contextualize_problems,
    problem_from_exception,
)
from scopecat.kernel.errors import ProblemFailure, RunPersistenceError
from scopecat.kernel.problems import ProblemCategory, ProblemPhase
from scopecat.measurements.results import MeasurementRecord
from scopecat.records.execution import InstrumentStateEvidence
from scopecat.records.run import RunManifest, RunOutcome
from scopecat.runs.access import upsert_artifacts, upsert_datasets, upsert_records
from scopecat.runs.refs import MANIFEST_REF
from scopecat.runs.repository import RunRepository


def commit_terminal_evidence(
    *,
    storage: RunRepository,
    run_id: str,
    outcome: RunOutcome,
    instrument_state: InstrumentStateEvidence | None,
    measurements: Sequence[MeasurementRecord],
    manifest: RunManifest,
) -> RunManifest:
    """Commit terminal content before publishing the terminal manifest marker.

    Instrument-backed execution supplies state evidence. Other execution domains
    omit it instead of publishing an empty record that claims instrument state was
    observed.
    """

    committed_refs: list[str] = []
    phase = "run_outcome"
    pending_ref = run_outcome_ref()
    try:
        storage.write_model(run_id, pending_ref, outcome)
        committed_refs.append(pending_ref)
        if instrument_state is not None:
            phase = "instrument_state_evidence"
            pending_ref = instrument_state_evidence_ref()
            storage.write_model(
                run_id,
                pending_ref,
                instrument_state,
            )
            committed_refs.append(pending_ref)
        if measurements:
            phase = "measurement_dataset"
            pending_ref = raw_measurements_ref()
            storage.write_jsonl(run_id, pending_ref, measurements)
            committed_refs.append(pending_ref)
        phase = "terminal_manifest"
        pending_ref = MANIFEST_REF
        with storage.run_lock(run_id):
            current = storage.read_manifest(run_id)
            committed_manifest = manifest.model_copy(
                update={
                    "records": upsert_records(current.records, manifest.records),
                    "datasets": upsert_datasets(current.datasets, manifest.datasets),
                    "artifacts": upsert_artifacts(
                        current.artifacts,
                        manifest.artifacts,
                    ),
                }
            )
            storage.write_manifest(committed_manifest)
        committed_refs.append(pending_ref)
        return committed_manifest
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

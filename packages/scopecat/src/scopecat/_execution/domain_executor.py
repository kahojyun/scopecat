"""Execute one prepared domain invocation as a standard durable Run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scopecat._compiler.run_plan import build_domain_run_plan_record
from scopecat._execution.events import emit_run_finished, emit_run_started
from scopecat._execution.evidence import (
    RAW_MEASUREMENTS_DATASET_ID,
    build_execution_manifest,
    raw_measurement_schema,
)
from scopecat._execution.persistence import (
    validate_measurement_index_shape,
    validate_raw_measurement_dataset,
)
from scopecat._execution.problems import (
    contextualize_problems,
    problem_from_exception,
    runtime_problem,
)
from scopecat._execution.program import ResourceClaim
from scopecat._execution.run_lifecycle import commit_terminal_evidence
from scopecat._storage.local import (
    LocalExecutionJournal,
    LocalMeasurementRecordCommitter,
    LocalResourceLeaseManager,
    LocalRunStore,
)
from scopecat.domain_execution import (
    PreparedDomainExecution,
    project_domain_run_plan_execution,
)
from scopecat.domain_runtime import (
    CorrelatedDomainFetch,
    fetch_domain_invocation,
    plan_domain_submission,
    submit_domain_invocation,
)
from scopecat.errors import (
    DomainFetchFailed,
    DomainRuntimeFailure,
    DomainRuntimePersistenceError,
    DomainSubmissionIndeterminate,
    MeasurementRecordingError,
    ProblemFailure,
    RunFailed,
    RunIndeterminate,
)
from scopecat.ids import new_run_id
from scopecat.measurement_projection import project_measurement_records
from scopecat.measurement_recording import commit_projected_measurement_records
from scopecat.measurement_transforms import execute_host_measurement_transforms
from scopecat.measurement_values import (
    ClosedMeasurementProductValues,
    assemble_measurement_values,
    domain_output_fragment,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.execution import ExecutionSummary
from scopecat.models.run import RunConfigSource, RunManifest, RunOutcome
from scopecat.models.run_request import RunRequest
from scopecat.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    has_blocking_problems,
)
from scopecat.runtime import RuntimeEventSink


@dataclass(slots=True)
class DomainSynchronousCompletionPending(Exception):
    """A synchronous unit returned a durable pending target job."""

    operation_id: str
    job_id: str
    submission_key: str


def execute_domain_job_values(
    prepared: PreparedDomainExecution,
    *,
    run_id: str,
    journal: LocalExecutionJournal,
) -> ClosedMeasurementProductValues:
    """Execute one closed domain job and return producer-neutral values."""

    submission_id = plan_domain_submission(
        prepared.invocation,
        run_id=run_id,
        semantic_operation_id=prepared.semantic_operation_id,
    )
    submission = submit_domain_invocation(
        prepared.runtime,
        prepared.invocation,
        submission_id,
        journal=journal,
    )
    fetched = fetch_domain_invocation(
        prepared.runtime,
        prepared.invocation.intent,
        submission,
        journal=journal,
    )
    if not isinstance(fetched, CorrelatedDomainFetch):
        raise DomainSynchronousCompletionPending(
            operation_id=submission_id.fetch_operation_id,
            job_id=submission.job_id,
            submission_key=submission_id.submission_key,
        )
    outputs = prepared.realize(fetched)
    source = domain_output_fragment(prepared.source_fragment, outputs)
    return (
        assemble_measurement_values(source.selection, (source,))
        if prepared.transforms is None
        else execute_host_measurement_transforms(
            prepared.transforms,
            (source,),
        ).values
    )


def execute_domain_run(
    *,
    config: ConfigProfileSnapshot,
    prepared: PreparedDomainExecution,
    request: RunRequest | None,
    workspace: str | Path,
    config_source: RunConfigSource | None = None,
    event_sink: RuntimeEventSink | None = None,
) -> tuple[RunManifest, ExecutionSummary]:
    """Durably accept and execute one completely prepared domain program."""

    run_id = new_run_id()
    plan = build_domain_run_plan_record(
        prepared.linked_points,
        prepared.projection,
        execution=project_domain_run_plan_execution(
            prepared,
            unit_id=f"domain-job-0-{prepared.adapter_id}",
        ),
        domain_product_use_ids=prepared.domain_product_use_ids,
    )
    storage = LocalRunStore(Path(workspace))
    accepted = RunManifest(
        run_id=run_id,
        lifecycle="accepted",
        config_source=config_source,
    )
    storage.write_run_skeleton(
        manifest=accepted,
        request=request,
        plan=plan,
        config=config,
    )
    storage.write_manifest(accepted.model_copy(update={"lifecycle": "running"}))

    experiment_id = plan.experiment_id
    point_count = plan.point_count
    emit_run_started(
        event_sink=event_sink,
        run_id=run_id,
        experiment_id=experiment_id,
        point_count=point_count,
        instrument_ids=[],
        output_ids=[record.id for record in plan.records],
    )

    journal = LocalExecutionJournal(workspace, run_id=run_id)
    committer = LocalMeasurementRecordCommitter(workspace, run_id=run_id)
    problems: list[Problem] = []
    certainty = "known"
    interruption: BaseException | None = None
    try:
        with LocalResourceLeaseManager(workspace).acquire(
            _domain_resource_claims(prepared)
        ):
            values = execute_domain_job_values(
                prepared,
                run_id=run_id,
                journal=journal,
            )
        projected = project_measurement_records(
            prepared.projection,
            values,
            run_id=run_id,
        )
        commit_projected_measurement_records(projected, committer, journal)
    except DomainSynchronousCompletionPending as error:
        problems.append(
            runtime_problem(
                "domain_synchronous_completion_contract_violated",
                (
                    "the domain runtime returned pending after its adapter "
                    "declared synchronous completion"
                ),
                run_id=run_id,
                operation_id=error.operation_id,
                category=ProblemCategory.PROVIDER_CONTRACT,
                details={
                    "completion_contract": prepared.completion_contract,
                    "job_id": error.job_id,
                    "submission_key": error.submission_key,
                    "automatic_resume": False,
                    "operator_action": "inspect_target_job",
                },
            )
        )
        certainty = "indeterminate"
    except (DomainRuntimeFailure, DomainRuntimePersistenceError) as error:
        problems.extend(
            contextualize_problems(
                error.problems,
                run_id=run_id,
                operation_id=error.operation_id,
            )
        )
        problems.append(
            domain_runtime_terminal_problem(
                error,
                run_id=run_id,
            )
        )
        if (
            isinstance(error, DomainSubmissionIndeterminate)
            or (
                isinstance(error, DomainFetchFailed)
                and error.certainty == "indeterminate"
            )
            or (
                isinstance(error, DomainRuntimePersistenceError)
                and error.certainty == "indeterminate"
            )
        ):
            certainty = "indeterminate"
    except MeasurementRecordingError as error:
        problems.extend(
            contextualize_problems(
                error.problems,
                run_id=run_id,
                operation_id=error.operation_id,
            )
        )
        problems.append(
            measurement_recording_terminal_problem(
                error,
                run_id=run_id,
            )
        )
        if error.write_may_have_completed:
            certainty = "indeterminate"
    except ProblemFailure as error:
        problems.extend(
            contextualize_problems(
                error.problems,
                run_id=run_id,
                operation_id=prepared.semantic_operation_id,
            )
        )
    except Exception as error:
        problems.append(
            problem_from_exception(
                "domain_execution_failed",
                "domain execution raised outside its structured contract",
                run_id=run_id,
                operation_id=prepared.semantic_operation_id,
                error=error,
            )
        )
    except BaseException as error:
        interruption = error
        problems.append(
            runtime_problem(
                "domain_execution_interrupted",
                "domain execution was interrupted",
                run_id=run_id,
                operation_id=prepared.semantic_operation_id,
                phase=ProblemPhase.EXECUTION,
                category=ProblemCategory.OPERATION,
                details={"exception_type": type(error).__qualname__},
            )
        )
        certainty = "indeterminate"

    try:
        measurements = list(committer.measurements())
    except Exception as error:
        measurements = []
        problems.append(
            problem_from_exception(
                "domain_measurement_reload_failed",
                "committed domain measurements could not be reloaded",
                run_id=run_id,
                operation_id="domain.measurements.reload",
                error=error,
                phase=ProblemPhase.PERSISTENCE,
                category=ProblemCategory.STORAGE,
            )
        )
        problems.append(
            runtime_problem(
                "domain_measurement_reload_terminalized",
                (
                    "the domain run was terminalized without trusting the "
                    "durable measurement chunk set"
                ),
                run_id=run_id,
                operation_id="domain.measurements.reload",
                phase=ProblemPhase.PERSISTENCE,
                category=ProblemCategory.STORAGE,
                details={
                    "storage_ref": "execution-measurements",
                    "reconciliation": (
                        "inspect and validate the run's durable measurement chunks"
                    ),
                    "automatic_resume": False,
                },
            )
        )
        certainty = "indeterminate"
    expected_schema = raw_measurement_schema(plan.expected_dataset_schema)
    problems.extend(
        validate_measurement_index_shape(
            measurements=measurements,
            expected_indices=set(range(point_count)),
            duplicate_code="domain_measurement_point_duplicate",
            duplicate_message="domain measurements repeat point index",
            unknown_code="domain_measurement_point_unknown",
            unknown_message="domain measurements contain unknown point index",
            missing_observables_code="domain_measurement_observables_missing",
            missing_observables_message=(
                "domain measurement records require at least one observable"
            ),
        )
    )
    problems.extend(
        validate_raw_measurement_dataset(
            records=measurements,
            expected_schema=expected_schema,
            dataset_id=RAW_MEASUREMENTS_DATASET_ID,
        )
    )
    completed_point_count = len({record.point_index for record in measurements})
    failed = has_blocking_problems(problems)
    outcome = RunOutcome(
        run_id=run_id,
        result=(
            "cancelled"
            if interruption is not None
            else "failed"
            if failed
            else "succeeded"
        ),
        certainty=("indeterminate" if certainty == "indeterminate" else "known"),
        termination_reason=(
            "interrupted"
            if interruption is not None
            else "effect_outcome_unknown"
            if certainty == "indeterminate"
            else "blocking_problem"
            if failed
            else "completed"
        ),
        problems=tuple(problems),
    )
    summary = ExecutionSummary(
        run_id=run_id,
        experiment_id=experiment_id,
        outcome=outcome,
        point_count=point_count,
        completed_point_count=completed_point_count,
        measurement_count=len(measurements),
        instrument_ids=[],
        problem_count=len(problems),
        problems=tuple(problems),
    )
    manifest = build_execution_manifest(
        run_id=run_id,
        outcome=outcome,
        measurements=measurements,
        expected_schema=expected_schema,
        config_source=config_source,
        include_instrument_state=False,
    ).model_copy(update={"created_at": accepted.created_at})
    commit_terminal_evidence(
        storage=storage,
        run_id=run_id,
        outcome=outcome,
        summary=summary,
        instrument_state=None,
        measurements=measurements,
        manifest=manifest,
    )
    emit_run_finished(
        event_sink=event_sink,
        run_id=run_id,
        experiment_id=experiment_id,
        outcome=outcome,
        completed_point_count=completed_point_count,
        point_count=point_count,
        measurement_count=len(measurements),
        problem_count=len(problems),
        compute_evaluated_node_count=0,
        compute_reused_node_count=0,
        compute_payload_count=0,
    )
    if interruption is not None:
        interruption.add_note(f"Scopecat run_id: {run_id}")
        raise interruption
    if outcome.result != "succeeded":
        if outcome.certainty == "indeterminate":
            raise RunIndeterminate(run_id=run_id, outcome=outcome)
        raise RunFailed(run_id=run_id, outcome=outcome)
    return manifest, summary


def domain_runtime_terminal_problem(
    error: DomainRuntimeFailure | DomainRuntimePersistenceError,
    *,
    run_id: str,
) -> Problem:
    """Retain actionable target correlation after terminalizing this v1 run."""

    details: dict[str, object] = {
        "phase": error.phase,
        "attempt": error.attempt,
        "invocation_id": error.invocation_id,
        "submission_key": error.submission_key,
        "retry_contract": error.retry,
        "reconciliation": error.reconciliation,
        "automatic_resume": False,
    }
    if error.job_id is not None:
        details["job_id"] = error.job_id
    return runtime_problem(
        "domain_runtime_terminalized",
        (
            "the synchronous domain run was terminalized with target "
            "correlation retained; automatic resume is not available"
        ),
        run_id=run_id,
        operation_id=error.operation_id,
        category=ProblemCategory.OPERATION,
        details=details,
    )


def measurement_recording_terminal_problem(
    error: MeasurementRecordingError,
    *,
    run_id: str,
) -> Problem:
    """Retain idempotent record correlation after terminalizing this v1 run."""

    details: dict[str, object] = {
        "dataset_id": error.dataset_id,
        "recording_contract_fingerprint": error.recording_contract_fingerprint,
        "attempt": error.attempt,
        "logical_point_id": error.logical_point_id,
        "point_index": error.point_index,
        "committed_record_refs": [
            receipt.record_ref for receipt in error.committed_prefix
        ],
        "write_may_have_completed": error.write_may_have_completed,
        "retry_contract": error.retry,
        "reconciliation": error.reconciliation,
        "automatic_resume": False,
    }
    if error.pending_receipt is not None:
        details["pending_record_ref"] = error.pending_receipt.record_ref
    return runtime_problem(
        "measurement_recording_terminalized",
        (
            "the synchronous domain run was terminalized with measurement "
            "record correlation retained; automatic resume is not available"
        ),
        run_id=run_id,
        operation_id=error.operation_id,
        point_index=error.point_index,
        phase=ProblemPhase.PERSISTENCE,
        category=ProblemCategory.STORAGE,
        details=details,
    )


def _domain_resource_claims(
    prepared: PreparedDomainExecution,
) -> tuple[ResourceClaim, ...]:
    claims = prepared.resource_claims
    if not claims:
        return (
            ResourceClaim(
                id=prepared.invocation.intent.target_id,
                kind="target",
            ),
        )
    return tuple(ResourceClaim(id=claim.id, kind=claim.kind) for claim in claims)


__all__ = [
    "DomainSynchronousCompletionPending",
    "domain_runtime_terminal_problem",
    "execute_domain_job_values",
    "execute_domain_run",
    "measurement_recording_terminal_problem",
]

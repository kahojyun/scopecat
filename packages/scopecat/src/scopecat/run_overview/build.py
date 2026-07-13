"""Stable local run overview assembly.

Run overviews are assembled from the persisted run manifest plus the optional
workflow records registered on that run: analysis records, parameter change
proposals and decisions, run comparisons and reviews, and config source
coordinates. Missing optional records are omitted from the overview instead of
being treated as part of the required run contract.
"""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel, ValidationError

from scopecat.application.services import WorkspaceServices
from scopecat.config.changes import (
    ParameterChangeDecisionRecord,
    list_parameter_change_decisions,
)
from scopecat.kernel.errors import DataIntegrityError, NotFound
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemLocation,
    ProblemPhase,
    StorageLocation,
    blocking_problem,
    model_location,
)
from scopecat.records.analysis import AnalysisRecord
from scopecat.records.artifact import RunDatasetEntry, RunRecordEntry
from scopecat.records.execution import ExecutionSummary
from scopecat.records.measurement import MeasurementDatasetSchema
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.records.run import RunManifest
from scopecat.run_comparison import (
    RunComparisonResult,
    RunComparisonReviewRecord,
)
from scopecat.run_overview.models import (
    AnalysisRecordEntry,
    DatasetOverviewEntry,
    DatasetVariableEntry,
    ExecutionOverviewEntry,
    ParameterChangeDecisionEvent,
    ParameterChangeDecisionInfo,
    ParameterChangeProposalEntry,
    RunComparisonEntry,
    RunHeader,
    RunOverview,
    RuntimeExecutionEntry,
    StateExecutionEntry,
)
from scopecat.runs.access import (
    list_records,
    record_storage_ref,
    storage_ref,
)
from scopecat.runs.repository import RunRepository


def build_run_overview(*, run_id: str, services: WorkspaceServices) -> RunOverview:
    storage = services.runs
    manifest = storage.read_manifest(run_id)
    _validate_manifest_entries(storage=storage, run_id=run_id, manifest=manifest)

    analysis_records = _read_analysis_records(
        storage=storage,
        run_id=run_id,
        manifest=manifest,
    )
    execution = _read_execution_overview(
        storage=storage,
        run_id=run_id,
        manifest=manifest,
    )
    datasets = _dataset_overviews(manifest)
    parameter_change_proposals = _read_parameter_change_proposals(
        storage=storage, run_id=run_id, manifest=manifest
    )
    run_comparisons = _read_run_comparisons(
        storage=storage, run_id=run_id, manifest=manifest
    )
    return RunOverview(
        run_id=run_id,
        run=RunHeader(
            run_id=manifest.run_id,
            status=manifest.status,
            created_at=manifest.created_at,
        ),
        config_source=manifest.config_source,
        execution=execution,
        datasets=datasets,
        analysis_records=analysis_records,
        parameter_change_proposals=parameter_change_proposals,
        run_comparisons=run_comparisons,
    )


def _read_execution_overview(
    *, storage: RunRepository, run_id: str, manifest: RunManifest
) -> ExecutionOverviewEntry | None:
    summary_records = _records_by_kind(manifest, "execution_summary")
    if not summary_records:
        return None
    summary_record = summary_records[0]
    summary_ref = record_storage_ref(summary_record)
    summary = _read_model(
        storage,
        run_id,
        summary_ref,
        ExecutionSummary,
    )
    state = StateExecutionEntry(
        changed_field_count=summary.state.changed_field_count,
        skipped_field_count=summary.state.skipped_field_count,
        state_command_count=summary.state.state_command_count,
        payload_count=summary.state.payload_count,
    )
    return ExecutionOverviewEntry(
        experiment_id=summary.experiment_id,
        status=summary.status,
        point_count=summary.point_count,
        measurement_count=summary.measurement_count,
        instrument_ids=list(summary.instrument_ids),
        problem_count=summary.problem_count,
        runtime=_runtime_summary(summary),
        state=state,
    )


def _runtime_summary(summary: ExecutionSummary) -> RuntimeExecutionEntry:
    return RuntimeExecutionEntry(
        completed_point_count=summary.completed_point_count,
        compute_evaluated_node_count=summary.compute.evaluated_node_count,
        compute_reused_node_count=summary.compute.reused_node_count,
        compute_payload_count=summary.compute.payload_count,
    )


def _dataset_overviews(manifest: RunManifest) -> list[DatasetOverviewEntry]:
    return [_dataset_overview(dataset) for dataset in manifest.datasets]


def _dataset_overview(dataset: RunDatasetEntry) -> DatasetOverviewEntry:
    schema = _dataset_schema(dataset)
    dimensions = (
        {
            dimension.id: dimension.size
            for dimension in schema.dimensions
            if dimension.size is not None
        }
        if schema is not None
        else {}
    )
    return DatasetOverviewEntry(
        id=dataset.id,
        kind=dataset.kind,
        role=dataset.role,
        record_count=_record_count(schema),
        coordinate_ids=list(schema.primary_coordinates) if schema is not None else [],
        observable_ids=list(schema.primary_observables) if schema is not None else [],
        dimensions=dimensions,
        variables=[
            DatasetVariableEntry(
                id=variable.id,
                role=variable.role,
                dtype=variable.dtype,
                unit=variable.unit,
                dims=list(variable.dims),
                shape=list(variable.shape),
            )
            for variable in schema.variables
        ]
        if schema is not None
        else [],
        metadata=dict(dataset.metadata),
    )


def _dataset_schema(dataset: RunDatasetEntry) -> MeasurementDatasetSchema | None:
    if dataset.data_schema is None:
        return None
    try:
        return MeasurementDatasetSchema.model_validate(dataset.data_schema)
    except ValidationError as error:
        raise DataIntegrityError(
            [
                _overview_problem(
                    "invalid_overview_input",
                    "overview input contains an invalid measurement schema",
                    location=model_location(
                        "run_manifest",
                        "datasets",
                        dataset.id,
                        "schema",
                    ),
                )
            ]
        ) from error


def _record_count(schema: MeasurementDatasetSchema | None) -> int | None:
    if schema is None:
        return None
    for dimension in schema.dimensions:
        if dimension.kind == "point" and dimension.size is not None:
            return dimension.size
    return None


def _read_analysis_records(
    *, storage: RunRepository, run_id: str, manifest: RunManifest
) -> list[AnalysisRecordEntry]:
    records: list[AnalysisRecordEntry] = []
    for record in _records_by_kind(manifest, "analysis"):
        record_ref = record_storage_ref(record)
        payload = _read_model(
            storage,
            run_id,
            record_ref,
            AnalysisRecord,
        )
        records.append(
            AnalysisRecordEntry(
                id=record.id,
                title=payload.title,
                output_kinds=[output.kind for output in payload.outputs],
                parameter_change_proposal_count=sum(
                    output.kind == "parameter_change_proposal"
                    for output in payload.outputs
                ),
                input_ids=_input_ids(payload),
                output_ids=_output_ids(payload),
            )
        )
    return records


def _read_parameter_change_proposals(
    *, storage: RunRepository, run_id: str, manifest: RunManifest
) -> list[ParameterChangeProposalEntry]:
    proposals: list[ParameterChangeProposalEntry] = []
    for proposal_record in list_records(
        manifest,
        kind="parameter_change_proposal",
    ):
        proposal_record_ref = record_storage_ref(proposal_record)
        proposal = _read_model(
            storage,
            run_id,
            proposal_record_ref,
            ParameterChangeProposal,
        )
        decision_info = _read_parameter_change_decision(
            storage=storage,
            run_id=run_id,
            proposal=proposal,
        )
        proposals.append(
            ParameterChangeProposalEntry(
                id=proposal.id,
                source_run_id=proposal.source_run_id,
                base_config_id=proposal.base_config_id,
                base_config_content_hash=proposal.base_config_content_hash,
                reason=proposal.reason,
                confidence=proposal.confidence,
                candidate_snapshot_id=proposal.candidate_snapshot.id,
                deltas=list(proposal.deltas),
                decision_info=decision_info,
            )
        )
    return proposals


def _read_parameter_change_decision(
    *, storage: RunRepository, run_id: str, proposal: ParameterChangeProposal
) -> ParameterChangeDecisionInfo:
    decisions = list_parameter_change_decisions(
        run_id=run_id,
        selector=proposal.id,
        storage=storage,
    )
    history = [_parameter_change_decision_event(decision) for decision in decisions]
    if not decisions:
        return ParameterChangeDecisionInfo(status="not_reviewed")
    decision = decisions[-1]
    return ParameterChangeDecisionInfo(
        status="reviewed",
        decision=decision.decision,
        actor=decision.actor,
        note=decision.note,
        decided_at=decision.decided_at,
        history=history,
    )


def _parameter_change_decision_event(
    decision: ParameterChangeDecisionRecord,
) -> ParameterChangeDecisionEvent:
    return ParameterChangeDecisionEvent(
        event_id=decision.event_id,
        decision=decision.decision,
        actor=decision.actor,
        note=decision.note,
        related_refs=list(decision.related_refs),
        decided_at=decision.decided_at,
    )


def _read_run_comparisons(
    *, storage: RunRepository, run_id: str, manifest: RunManifest
) -> list[RunComparisonEntry]:
    comparisons: list[RunComparisonEntry] = []
    for record in _records_by_kind(manifest, "run_comparison_result"):
        result_ref = record_storage_ref(record)
        result = _read_model(
            storage,
            run_id,
            result_ref,
            RunComparisonResult,
        )
        review_record_id = f"{result.comparison_id}-review"
        review_record = next(
            (
                candidate
                for candidate in manifest.records
                if candidate.id == review_record_id
            ),
            None,
        )
        review_ref = (
            record_storage_ref(review_record) if review_record is not None else None
        )
        review: RunComparisonReviewRecord | None = None
        if review_ref is not None and storage.exists(run_id, review_ref):
            review = _read_model(
                storage,
                run_id,
                review_ref,
                RunComparisonReviewRecord,
            )
        comparisons.append(
            RunComparisonEntry(
                comparison_id=result.comparison_id,
                baseline_run_id=result.baseline_run_id,
                candidate_run_id=result.candidate_run_id,
                observable_id=result.observable_id,
                outcome=result.outcome,
                measurement_count=result.measurement_count,
                baseline_peak_point_index=result.baseline_peak_point_index,
                candidate_peak_point_index=result.candidate_peak_point_index,
                baseline_peak_value=result.baseline_peak_value,
                candidate_peak_value=result.candidate_peak_value,
                peak_value_delta=result.peak_value_delta,
                mean_value_delta=result.mean_value_delta,
                value_unit=result.value_unit,
                baseline_config_source=result.baseline_config_source,
                candidate_config_source=result.candidate_config_source,
                review_status="reviewed" if review is not None else "not_reviewed",
                decision=review.decision if review is not None else None,
                reviewer=review.reviewer if review is not None else None,
                note=review.note if review is not None else None,
                reviewed_at=review.reviewed_at if review is not None else None,
                generated_at=result.generated_at,
            )
        )
    return comparisons


def _records_by_kind(manifest: RunManifest, kind: str) -> list[RunRecordEntry]:
    return sorted(
        list_records(manifest, kind=kind),
        key=lambda record: record.id,
    )


def _read_model[TModel: BaseModel](
    storage: RunRepository,
    run_id: str,
    ref: str,
    model_type: type[TModel],
) -> TModel:
    location = StorageLocation(run_id=run_id, ref=ref)
    kind = storage.ref_kind(run_id, ref)
    if kind == "missing":
        raise DataIntegrityError(
            [
                _overview_problem(
                    "missing_overview_input",
                    f"overview input is missing: {ref}",
                    location=location,
                )
            ]
        )
    if kind != "file":
        raise DataIntegrityError(
            [
                _overview_problem(
                    "overview_input_is_directory",
                    f"overview input is a directory: {ref}",
                    location=location,
                )
            ]
        )
    try:
        return storage.read_model(run_id, ref, model_type)
    except NotFound as error:
        raise DataIntegrityError(
            [
                _overview_problem(
                    "missing_overview_input",
                    f"overview input is missing: {ref}",
                    location=location,
                )
            ]
        ) from error
    except DataIntegrityError as error:
        raise DataIntegrityError(
            [
                _overview_problem(
                    "invalid_overview_input",
                    f"overview input is not valid JSON for {ref}",
                    location=location,
                )
            ]
        ) from error


def _validate_manifest_entries(
    *, storage: RunRepository, run_id: str, manifest: RunManifest
) -> None:
    entries = [*manifest.artifacts, *manifest.datasets, *manifest.records]
    for entry in entries:
        entry_storage_ref = storage_ref(entry)
        if storage.ref_kind(run_id, entry_storage_ref) == "directory":
            raise DataIntegrityError(
                [
                    _overview_problem(
                        "overview_ref_is_directory",
                        f"overview input is a directory: {entry_storage_ref}",
                        location=StorageLocation(
                            run_id=run_id,
                            ref=entry_storage_ref,
                        ),
                    )
                ]
            )


def _input_ids(payload: AnalysisRecord) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for input_ref in payload.inputs:
        key = f"{input_ref.kind}:{input_ref.target}"
        if key in seen:
            continue
        ids.append(key)
        seen.add(key)
    return ids


def _output_ids(payload: AnalysisRecord) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for output in payload.outputs:
        if output.kind != "artifact" or not isinstance(output.content, dict):
            continue
        content = cast(dict[str, object], output.content)
        artifact_id = content.get("artifact_id")
        if not isinstance(artifact_id, str) or artifact_id in seen:
            continue
        ids.append(artifact_id)
        seen.add(artifact_id)
    return ids


def _overview_problem(
    code: str,
    message: str,
    *,
    category: ProblemCategory = ProblemCategory.DATA_INTEGRITY,
    location: ProblemLocation,
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=category,
        phase=ProblemPhase.ANALYSIS,
        location=location,
    )

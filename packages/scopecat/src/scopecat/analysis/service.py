"""Application use cases for authoring and persisting run analyses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, NoReturn

from scopecat.analysis.datasets import (
    DERIVED_DATASET_CODEC,
    DERIVED_DATASET_MEDIA_TYPE,
    DerivedDataset,
)
from scopecat.config.changes import (
    parameter_change_proposal_record_ref,
    prepare_parameter_change_proposal_contents,
)
from scopecat.kernel.content_identity import (
    model_wire_content_hash,
    sha256_content_hash,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.ids import artifact_slug
from scopecat.kernel.problems import (
    LocationPathItem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.project_state import ProjectStateServices
from scopecat.records._metadata import validate_json_metadata
from scopecat.records.analysis import (
    AnalysisComputeExecution,
    AnalysisDataRecordOutput,
    AnalysisDatasetRecordOutput,
    AnalysisDatasetReference,
    AnalysisDerivedData,
    AnalysisFigure,
    AnalysisFigureRecordOutput,
    AnalysisParameterProposalRecordOutput,
    AnalysisParameterProposalReference,
    AnalysisRecord,
    AnalysisRecordInput,
    AnalysisRecordOutput,
    AnalysisTable,
    AnalysisTableRecordOutput,
)
from scopecat.records.artifact import RunContentEntry
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.runs.refs import dataset_content_ref, record_content_ref
from scopecat.runs.repository import (
    RunBytesWrite,
    RunContentPublication,
    RunModelWrite,
)


@dataclass(frozen=True)
class AnalysisInput:
    target: str
    kind: Literal["measurement_dataset"]
    role: str
    title: str | None = None
    metadata: Mapping[str, object] | None = None


@dataclass(frozen=True)
class AnalysisTableOutput:
    kind: Literal["table"]
    title: str
    content: AnalysisTable
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class AnalysisFigureOutput:
    kind: Literal["figure"]
    title: str
    content: AnalysisFigure
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class AnalysisParameterProposalOutput:
    kind: Literal["parameter_change_proposal"]
    title: str
    content: ParameterChangeProposal
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class AnalysisDataOutput:
    kind: Literal["data"]
    title: str
    content: AnalysisDerivedData
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class AnalysisDatasetOutput:
    kind: Literal["dataset"]
    id: str
    title: str
    content: DerivedDataset
    execution: AnalysisComputeExecution | None
    metadata: Mapping[str, object]


type AnalysisOutput = (
    AnalysisDataOutput
    | AnalysisDatasetOutput
    | AnalysisTableOutput
    | AnalysisFigureOutput
    | AnalysisParameterProposalOutput
)


@dataclass(frozen=True)
class SavedAnalysis:
    record: RunContentEntry
    analysis_key: str
    inputs: tuple[AnalysisInput, ...] = ()


@dataclass(frozen=True, slots=True)
class PreparedAnalysis:
    saved: SavedAnalysis
    publication: RunContentPublication


def save_analysis(
    *,
    services: ProjectStateServices,
    run_id: str,
    title: str,
    analysis_key: str,
    step_id: str | None,
    inputs: Sequence[AnalysisInput],
    outputs: Sequence[AnalysisOutput],
    parameter_proposals: Sequence[ParameterChangeProposal],
) -> SavedAnalysis:
    """Prepare and publish one analysis using the repository's local unit."""

    prepared = prepare_analysis(
        services=services,
        run_id=run_id,
        title=title,
        analysis_key=analysis_key,
        step_id=step_id,
        inputs=inputs,
        outputs=outputs,
        parameter_proposals=parameter_proposals,
    )
    services.runs.publish_content(prepared.publication)
    return prepared.saved


def prepare_analysis(
    *,
    services: ProjectStateServices,
    run_id: str,
    title: str,
    analysis_key: str,
    step_id: str | None,
    inputs: Sequence[AnalysisInput],
    outputs: Sequence[AnalysisOutput],
    parameter_proposals: Sequence[ParameterChangeProposal],
) -> PreparedAnalysis:
    """Prepare analysis content for publication in a caller-owned unit."""

    selected_record_id = f"analysis-{analysis_key}"
    if any(
        proposal.analysis_record_id != selected_record_id
        for proposal in parameter_proposals
    ):
        _raise_analysis_problem(
            "analysis_parameter_proposal_source_invalid",
            "analysis parameter proposal does not identify its producing analysis",
            "parameter_proposals",
        )
    ref = record_content_ref(record_id=selected_record_id, kind="analysis")
    storage = services.runs
    prepared_datasets = _prepare_analysis_datasets(
        analysis_record_id=selected_record_id,
        outputs=outputs,
    )
    analysis_record = AnalysisRecord(
        run_id=run_id,
        title=title,
        key=analysis_key,
        step_id=step_id,
        inputs=_analysis_record_inputs(inputs),
        outputs=_analysis_record_outputs(
            outputs,
            dataset_references=prepared_datasets.references,
        ),
    )
    record = RunContentEntry(
        role="record",
        id=selected_record_id,
        kind="analysis",
        media_type="application/json",
        content_hash=model_wire_content_hash(analysis_record),
    )
    prepared_proposals = prepare_parameter_change_proposal_contents(
        storage=storage,
        run_id=run_id,
        proposals=parameter_proposals,
    )
    saved = SavedAnalysis(
        record=record,
        analysis_key=analysis_key,
        inputs=tuple(inputs),
    )
    return PreparedAnalysis(
        saved=saved,
        publication=RunContentPublication(
            run_id=run_id,
            entries=(
                *prepared_proposals.entries,
                *prepared_datasets.entries,
                record,
            ),
            models=(
                *prepared_proposals.writes,
                RunModelWrite(ref=ref, value=analysis_record),
            ),
            bytes=prepared_datasets.writes,
        ),
    )


def _analysis_record_inputs(
    inputs: Sequence[AnalysisInput],
) -> list[AnalysisRecordInput]:
    record_inputs: list[AnalysisRecordInput] = []
    for input_ref in inputs:
        metadata = input_ref.metadata
        record_inputs.append(
            AnalysisRecordInput(
                target=input_ref.target,
                kind=input_ref.kind,
                role=input_ref.role,
                title=input_ref.title,
                metadata=(
                    validate_json_metadata(metadata) if metadata is not None else None
                ),
            )
        )
    return record_inputs


def _analysis_record_outputs(
    outputs: Sequence[AnalysisOutput],
    *,
    dataset_references: Mapping[str, AnalysisDatasetReference],
) -> list[AnalysisRecordOutput]:
    selected: list[AnalysisRecordOutput] = []
    for output in outputs:
        metadata = validate_json_metadata(output.metadata)
        if isinstance(output, AnalysisDataOutput):
            selected.append(
                AnalysisDataRecordOutput(
                    kind="data",
                    title=output.title,
                    content=output.content,
                    metadata=metadata,
                )
            )
        elif isinstance(output, AnalysisDatasetOutput):
            selected.append(
                AnalysisDatasetRecordOutput(
                    kind="dataset",
                    title=output.title,
                    content=dataset_references[output.id],
                    metadata=metadata,
                )
            )
        elif isinstance(output, AnalysisTableOutput):
            selected.append(
                AnalysisTableRecordOutput(
                    kind="table",
                    title=output.title,
                    content=output.content,
                    metadata=metadata,
                )
            )
        elif isinstance(output, AnalysisFigureOutput):
            selected.append(
                AnalysisFigureRecordOutput(
                    kind="figure",
                    title=output.title,
                    content=output.content,
                    metadata=metadata,
                )
            )
        else:
            selected.append(
                AnalysisParameterProposalRecordOutput(
                    kind="parameter_change_proposal",
                    title=output.title,
                    content=AnalysisParameterProposalReference(
                        proposal_id=output.content.id,
                        record_ref=parameter_change_proposal_record_ref(
                            output.content.id
                        ),
                    ),
                    metadata=metadata,
                )
            )
    return selected


@dataclass(frozen=True, slots=True)
class _PreparedAnalysisDatasets:
    entries: tuple[RunContentEntry, ...]
    writes: tuple[RunBytesWrite, ...]
    references: Mapping[str, AnalysisDatasetReference]


def _prepare_analysis_datasets(
    *,
    analysis_record_id: str,
    outputs: Sequence[AnalysisOutput],
) -> _PreparedAnalysisDatasets:
    entries: list[RunContentEntry] = []
    writes: list[RunBytesWrite] = []
    references: dict[str, AnalysisDatasetReference] = {}
    for output in outputs:
        if not isinstance(output, AnalysisDatasetOutput):
            continue
        output_id = artifact_slug(output.id, fallback="data")
        if output_id != output.id:
            _raise_analysis_problem(
                "analysis_dataset_id_invalid",
                f"analysis dataset id is not normalized: {output.id}",
                "outputs",
            )
        if output.id in references:
            _raise_analysis_problem(
                "analysis_dataset_id_duplicated",
                f"analysis dataset id is duplicated: {output.id}",
                "outputs",
            )
        dataset_id = f"{analysis_record_id}-{output.id}"
        content = output.content.to_arrow_ipc()
        content_hash = sha256_content_hash(content)
        if (
            output.execution is not None
            and output.execution.output_content_hash != content_hash
        ):
            _raise_analysis_problem(
                "analysis_dataset_execution_hash_mismatch",
                "analysis dataset content does not match its compute execution",
                "outputs",
            )
        metadata = validate_json_metadata(output.metadata)
        entries.append(
            RunContentEntry(
                role="dataset",
                id=dataset_id,
                kind="analysis_dataset",
                title=output.title,
                media_type=DERIVED_DATASET_MEDIA_TYPE,
                filename=f"{output.id}.arrow",
                schema=output.content.schema.model_dump(mode="json"),
                content_hash=content_hash,
                produced_by=analysis_record_id,
                metadata=metadata,
            )
        )
        writes.append(
            RunBytesWrite(
                ref=dataset_content_ref(
                    dataset_id=dataset_id,
                    kind="analysis_dataset",
                ),
                content=content,
            )
        )
        references[output.id] = AnalysisDatasetReference(
            output_id=output.id,
            dataset_id=dataset_id,
            content_hash=content_hash,
            codec=DERIVED_DATASET_CODEC,
            execution=output.execution,
        )
    return _PreparedAnalysisDatasets(
        entries=tuple(entries),
        writes=tuple(writes),
        references=references,
    )


def _raise_analysis_problem(
    code: str,
    message: str,
    *path: LocationPathItem,
) -> NoReturn:
    raise CheckFailed(
        [
            problem(
                code,
                message,
                phase=ProblemPhase.ANALYSIS,
                location=model_location("analysis", *path),
            )
        ]
    )

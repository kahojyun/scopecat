"""Application use cases for authoring and persisting run analyses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, NoReturn

from scopecat.config.changes import (
    parameter_change_proposal_record_ref,
    prepare_parameter_change_proposal_contents,
)
from scopecat.kernel.content_identity import (
    model_wire_content_hash,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    LocationPathItem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat.project_state import ProjectStateServices
from scopecat.records._metadata import validate_json_metadata
from scopecat.records.analysis import (
    AnalysisDataRecordOutput,
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
from scopecat.runs.refs import record_content_ref
from scopecat.runs.repository import (
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


type AnalysisOutput = (
    AnalysisDataOutput
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
    analysis_record = AnalysisRecord(
        run_id=run_id,
        title=title,
        key=analysis_key,
        step_id=step_id,
        inputs=_analysis_record_inputs(inputs),
        outputs=_analysis_record_outputs(outputs),
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
                record,
            ),
            models=(
                *prepared_proposals.writes,
                RunModelWrite(ref=ref, value=analysis_record),
            ),
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

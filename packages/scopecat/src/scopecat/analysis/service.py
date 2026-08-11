"""Application use cases for authoring and persisting run analyses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal, NoReturn

from scopecat.analysis.datasets import (
    DERIVED_DATASET_CODEC,
    DERIVED_DATASET_MEDIA_TYPE,
    DerivedDataset,
)
from scopecat.config.changes import (
    load_parameter_change_proposal,
    parameter_change_proposal_record_ref,
    prepare_parameter_change_proposal_contents,
)
from scopecat.kernel.content_identity import (
    content_fingerprint,
    model_wire_content_hash,
    sha256_content_hash,
    stable_content_hash,
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
    AnalysisArtifactRecordOutput,
    AnalysisArtifactReference,
    AnalysisDatasetRecordOutput,
    AnalysisDatasetReference,
    AnalysisExecution,
    AnalysisExecutionOutputReference,
    AnalysisFact,
    AnalysisFactRecordOutput,
    AnalysisFigureRecordOutput,
    AnalysisFigureView,
    AnalysisParameterProposalRecordOutput,
    AnalysisParameterProposalReference,
    AnalysisRecord,
    AnalysisRecordInput,
    AnalysisRecordOutput,
    AnalysisTableRecordOutput,
    AnalysisTableView,
)
from scopecat.records.artifact import RunContentEntry
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.runs.access import list_records
from scopecat.runs.refs import (
    artifact_content_ref,
    dataset_content_ref,
    record_content_ref,
)
from scopecat.runs.repository import (
    RunBytesWrite,
    RunContentPublication,
    RunModelWrite,
)


@dataclass(frozen=True)
class AnalysisInput:
    target: str
    kind: Literal["measurement_dataset"]
    content_hash: str
    codec: str
    role: str
    title: str | None = None
    metadata: Mapping[str, object] | None = None


@dataclass(frozen=True)
class AnalysisTableOutput:
    kind: Literal["table"]
    id: str
    title: str
    content: AnalysisTableView
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class AnalysisFigureOutput:
    kind: Literal["figure"]
    id: str
    title: str
    content: AnalysisFigureView
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class AnalysisParameterProposalOutput:
    kind: Literal["parameter_change_proposal"]
    id: str
    title: str
    content: ParameterChangeProposal
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class AnalysisFactOutput:
    kind: Literal["fact"]
    id: str
    title: str
    content: AnalysisFact
    metadata: Mapping[str, object]
    produced_by: AnalysisExecutionOutputReference | None = None


@dataclass(frozen=True)
class AnalysisDatasetOutput:
    kind: Literal["dataset"]
    id: str
    title: str
    content: DerivedDataset
    metadata: Mapping[str, object]
    produced_by: AnalysisExecutionOutputReference | None = None


@dataclass(frozen=True)
class AnalysisArtifactOutput:
    kind: Literal["artifact"]
    id: str
    title: str
    content: bytes
    filename: str
    media_type: str
    metadata: Mapping[str, object]


type AnalysisOutput = (
    AnalysisFactOutput
    | AnalysisDatasetOutput
    | AnalysisArtifactOutput
    | AnalysisTableOutput
    | AnalysisFigureOutput
    | AnalysisParameterProposalOutput
)


@dataclass(frozen=True)
class SavedAnalysis:
    record: RunContentEntry
    analysis_key: str
    inputs: tuple[AnalysisInput, ...] = ()
    executions: tuple[AnalysisExecution, ...] = ()
    outputs: tuple[AnalysisOutput, ...] = ()
    parameter_proposals: tuple[ParameterChangeProposal, ...] = ()


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
    executions: Sequence[AnalysisExecution],
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
        executions=executions,
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
    executions: Sequence[AnalysisExecution],
    outputs: Sequence[AnalysisOutput],
    parameter_proposals: Sequence[ParameterChangeProposal],
) -> PreparedAnalysis:
    """Prepare analysis content for publication in a caller-owned unit."""

    base_record_id = f"analysis-{analysis_key}"
    _validate_analysis_output_ids(outputs)
    _validate_analysis_execution_outputs(executions, outputs)
    output_proposals = tuple(
        output.content
        for output in outputs
        if isinstance(output, AnalysisParameterProposalOutput)
    )
    if output_proposals != tuple(parameter_proposals):
        _raise_analysis_problem(
            "analysis_parameter_proposals_mismatch",
            "analysis parameter proposals must match proposal outputs",
            "parameter_proposals",
        )
    if any(
        proposal.analysis_record_id != base_record_id
        for proposal in parameter_proposals
    ):
        _raise_analysis_problem(
            "analysis_parameter_proposal_source_invalid",
            "analysis parameter proposal does not identify its producing analysis",
            "parameter_proposals",
        )
    publication_hash = _analysis_publication_hash(
        title=title,
        analysis_key=analysis_key,
        step_id=step_id,
        inputs=inputs,
        executions=executions,
        outputs=outputs,
    )
    existing = _latest_analysis(
        services=services,
        run_id=run_id,
        analysis_key=analysis_key,
    )
    if existing is not None and existing.record.publication_hash == publication_hash:
        saved_outputs = _load_existing_outputs(
            services=services,
            run_id=run_id,
            outputs=outputs,
            record=existing.record,
        )
        saved_proposals = tuple(
            output.content
            for output in saved_outputs
            if isinstance(output, AnalysisParameterProposalOutput)
        )
        return PreparedAnalysis(
            saved=SavedAnalysis(
                record=existing.entry,
                analysis_key=analysis_key,
                inputs=tuple(inputs),
                executions=tuple(existing.record.executions),
                outputs=saved_outputs,
                parameter_proposals=saved_proposals,
            ),
            publication=RunContentPublication(run_id=run_id, entries=()),
        )

    revision = 1 if existing is None else existing.record.revision + 1
    selected_record_id = (
        base_record_id if revision == 1 else f"{base_record_id}-r{revision}"
    )
    saved_outputs = _revisioned_outputs(
        outputs,
        analysis_record_id=selected_record_id,
        revision=revision,
    )
    saved_proposals = tuple(
        output.content
        for output in saved_outputs
        if isinstance(output, AnalysisParameterProposalOutput)
    )
    ref = record_content_ref(record_id=selected_record_id, kind="analysis")
    storage = services.runs
    prepared_datasets = _prepare_analysis_datasets(
        analysis_record_id=selected_record_id,
        outputs=saved_outputs,
    )
    prepared_artifacts = _prepare_analysis_artifacts(
        analysis_record_id=selected_record_id,
        outputs=saved_outputs,
    )
    analysis_record = AnalysisRecord(
        run_id=run_id,
        title=title,
        key=analysis_key,
        revision=revision,
        publication_hash=publication_hash,
        step_id=step_id,
        inputs=_analysis_record_inputs(inputs),
        executions=list(executions),
        outputs=_analysis_record_outputs(
            saved_outputs,
            dataset_references=prepared_datasets.references,
            artifact_references=prepared_artifacts.references,
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
        proposals=saved_proposals,
    )
    saved = SavedAnalysis(
        record=record,
        analysis_key=analysis_key,
        inputs=tuple(inputs),
        executions=tuple(executions),
        outputs=saved_outputs,
        parameter_proposals=saved_proposals,
    )
    return PreparedAnalysis(
        saved=saved,
        publication=RunContentPublication(
            run_id=run_id,
            entries=(
                *prepared_proposals.entries,
                *prepared_datasets.entries,
                *prepared_artifacts.entries,
                record,
            ),
            models=(
                *prepared_proposals.writes,
                RunModelWrite(ref=ref, value=analysis_record),
            ),
            bytes=(*prepared_datasets.writes, *prepared_artifacts.writes),
        ),
    )


@dataclass(frozen=True, slots=True)
class _ExistingAnalysis:
    entry: RunContentEntry
    record: AnalysisRecord


def _latest_analysis(
    *,
    services: ProjectStateServices,
    run_id: str,
    analysis_key: str,
) -> _ExistingAnalysis | None:
    storage = services.runs
    matches: list[_ExistingAnalysis] = []
    for entry in list_records(storage.read_manifest(run_id), kind="analysis"):
        record = storage.read_model(
            run_id,
            record_content_ref(record_id=entry.id, kind="analysis"),
            AnalysisRecord,
        )
        if record.key == analysis_key:
            matches.append(_ExistingAnalysis(entry=entry, record=record))
    return max(matches, key=lambda item: item.record.revision, default=None)


def _revisioned_outputs(
    outputs: Sequence[AnalysisOutput],
    *,
    analysis_record_id: str,
    revision: int,
) -> tuple[AnalysisOutput, ...]:
    selected: list[AnalysisOutput] = []
    for output in outputs:
        if not isinstance(output, AnalysisParameterProposalOutput):
            selected.append(output)
            continue
        proposal_id = output.id if revision == 1 else f"{output.id}-r{revision}"
        selected.append(
            replace(
                output,
                content=output.content.model_copy(
                    update={
                        "id": proposal_id,
                        "analysis_record_id": analysis_record_id,
                    }
                ),
            )
        )
    return tuple(selected)


def _load_existing_outputs(
    *,
    services: ProjectStateServices,
    run_id: str,
    outputs: Sequence[AnalysisOutput],
    record: AnalysisRecord,
) -> tuple[AnalysisOutput, ...]:
    proposal_ids = {
        output.id: output.content.proposal_id
        for output in record.outputs
        if isinstance(output, AnalysisParameterProposalRecordOutput)
    }
    selected: list[AnalysisOutput] = []
    for output in outputs:
        if not isinstance(output, AnalysisParameterProposalOutput):
            selected.append(output)
            continue
        selected.append(
            replace(
                output,
                content=load_parameter_change_proposal(
                    run_id=run_id,
                    selector=proposal_ids[output.id],
                    services=services,
                ),
            )
        )
    return tuple(selected)


def _analysis_publication_hash(
    *,
    title: str,
    analysis_key: str,
    step_id: str | None,
    inputs: Sequence[AnalysisInput],
    executions: Sequence[AnalysisExecution],
    outputs: Sequence[AnalysisOutput],
) -> str:
    identity = {
        "title": title,
        "key": analysis_key,
        "step_id": step_id,
        "inputs": [
            {
                "target": item.target,
                "kind": item.kind,
                "content_hash": item.content_hash,
                "codec": item.codec,
                "role": item.role,
                "title": item.title,
                "metadata": validate_json_metadata(item.metadata or {}),
            }
            for item in inputs
        ],
        "executions": list(executions),
        "outputs": [_analysis_output_identity(output) for output in outputs],
    }
    return f"sha256:{stable_content_hash(content_fingerprint(identity))}"


def _analysis_output_identity(output: AnalysisOutput) -> dict[str, object]:
    shared: dict[str, object] = {
        "kind": output.kind,
        "id": output.id,
        "title": output.title,
        "metadata": validate_json_metadata(output.metadata),
    }
    if isinstance(output, AnalysisDatasetOutput):
        shared["produced_by"] = output.produced_by
        shared["content"] = {
            "content_hash": sha256_content_hash(output.content.to_arrow_ipc()),
            "schema": output.content.schema.model_dump(mode="json"),
        }
    elif isinstance(output, AnalysisArtifactOutput):
        shared["content"] = {
            "content_hash": sha256_content_hash(output.content),
            "filename": output.filename,
            "media_type": output.media_type,
        }
    elif isinstance(output, AnalysisParameterProposalOutput):
        proposal = output.content
        shared["content"] = {
            "source_run_id": proposal.source_run_id,
            "base_config_id": proposal.base_config_id,
            "base_config_content_hash": proposal.base_config_content_hash,
            "reason": proposal.reason,
            "confidence": proposal.confidence,
            "deltas": proposal.deltas,
        }
    elif isinstance(output, AnalysisFactOutput):
        shared["produced_by"] = output.produced_by
        shared["content"] = output.content
    else:
        shared["content"] = output.content
    return shared


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
                content_hash=input_ref.content_hash,
                codec=input_ref.codec,
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
    artifact_references: Mapping[str, AnalysisArtifactReference],
) -> list[AnalysisRecordOutput]:
    selected: list[AnalysisRecordOutput] = []
    for output in outputs:
        metadata = validate_json_metadata(output.metadata)
        if isinstance(output, AnalysisFactOutput):
            selected.append(
                AnalysisFactRecordOutput(
                    kind="fact",
                    id=output.id,
                    title=output.title,
                    content=output.content,
                    produced_by=output.produced_by,
                    metadata=metadata,
                )
            )
        elif isinstance(output, AnalysisDatasetOutput):
            selected.append(
                AnalysisDatasetRecordOutput(
                    kind="dataset",
                    id=output.id,
                    title=output.title,
                    content=dataset_references[output.id],
                    produced_by=output.produced_by,
                    metadata=metadata,
                )
            )
        elif isinstance(output, AnalysisArtifactOutput):
            selected.append(
                AnalysisArtifactRecordOutput(
                    kind="artifact",
                    id=output.id,
                    title=output.title,
                    content=artifact_references[output.id],
                    metadata=metadata,
                )
            )
        elif isinstance(output, AnalysisTableOutput):
            selected.append(
                AnalysisTableRecordOutput(
                    kind="table",
                    id=output.id,
                    title=output.title,
                    content=output.content,
                    metadata=metadata,
                )
            )
        elif isinstance(output, AnalysisFigureOutput):
            selected.append(
                AnalysisFigureRecordOutput(
                    kind="figure",
                    id=output.id,
                    title=output.title,
                    content=output.content,
                    metadata=metadata,
                )
            )
        else:
            selected.append(
                AnalysisParameterProposalRecordOutput(
                    kind="parameter_change_proposal",
                    id=output.id,
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
            dataset_id=dataset_id,
            content_hash=content_hash,
            codec=DERIVED_DATASET_CODEC,
        )
    return _PreparedAnalysisDatasets(
        entries=tuple(entries),
        writes=tuple(writes),
        references=references,
    )


@dataclass(frozen=True, slots=True)
class _PreparedAnalysisArtifacts:
    entries: tuple[RunContentEntry, ...]
    writes: tuple[RunBytesWrite, ...]
    references: Mapping[str, AnalysisArtifactReference]


def _prepare_analysis_artifacts(
    *,
    analysis_record_id: str,
    outputs: Sequence[AnalysisOutput],
) -> _PreparedAnalysisArtifacts:
    entries: list[RunContentEntry] = []
    writes: list[RunBytesWrite] = []
    references: dict[str, AnalysisArtifactReference] = {}
    for output in outputs:
        if not isinstance(output, AnalysisArtifactOutput):
            continue
        artifact_id = f"{analysis_record_id}-{output.id}"
        content_hash = sha256_content_hash(output.content)
        metadata = validate_json_metadata(output.metadata)
        entries.append(
            RunContentEntry(
                role="artifact",
                id=artifact_id,
                kind="analysis_artifact",
                title=output.title,
                media_type=output.media_type,
                filename=output.filename,
                content_hash=content_hash,
                produced_by=analysis_record_id,
                metadata=metadata,
            )
        )
        writes.append(
            RunBytesWrite(
                ref=artifact_content_ref(
                    artifact_id=artifact_id,
                    kind="analysis_artifact",
                ),
                content=output.content,
            )
        )
        references[output.id] = AnalysisArtifactReference(
            artifact_id=artifact_id,
            content_hash=content_hash,
            media_type=output.media_type,
            filename=output.filename,
        )
    return _PreparedAnalysisArtifacts(
        entries=tuple(entries),
        writes=tuple(writes),
        references=references,
    )


def _validate_analysis_output_ids(outputs: Sequence[AnalysisOutput]) -> None:
    ids: list[str] = []
    for output in outputs:
        selected_id = artifact_slug(output.id, fallback="output")
        if output.id != selected_id:
            _raise_analysis_problem(
                "analysis_output_id_invalid",
                f"analysis output id is not normalized: {output.id}",
                "outputs",
            )
        ids.append(output.id)
    if len(ids) != len(set(ids)):
        _raise_analysis_problem(
            "analysis_output_id_duplicated",
            "analysis output ids must be unique",
            "outputs",
        )


def _validate_analysis_execution_outputs(
    executions: Sequence[AnalysisExecution],
    outputs: Sequence[AnalysisOutput],
) -> None:
    execution_by_id = {execution.id: execution for execution in executions}
    if len(execution_by_id) != len(executions):
        _raise_analysis_problem(
            "analysis_execution_id_duplicated",
            "analysis execution ids must be unique",
            "executions",
        )
    for output in outputs:
        if not isinstance(output, AnalysisDatasetOutput | AnalysisFactOutput):
            continue
        if output.produced_by is None:
            continue
        producer = output.produced_by
        execution = execution_by_id.get(producer.execution_id)
        if execution is None:
            _raise_analysis_problem(
                "analysis_output_producer_unknown",
                "analysis output producer must identify an execution",
                "outputs",
            )
        if isinstance(output, AnalysisDatasetOutput):
            content_hash = sha256_content_hash(output.content.to_arrow_ipc())
            expected_kind = "derived_dataset"
            expected_codec = DERIVED_DATASET_CODEC
        else:
            content_hash = f"sha256:{stable_content_hash(output.content.value)}"
            expected_kind = "value"
            expected_codec = output.content.codec
        execution_output = next(
            (item for item in execution.outputs if item.name == producer.output_name),
            None,
        )
        if execution_output is None:
            _raise_analysis_problem(
                "analysis_output_producer_unknown",
                "analysis output producer must identify an execution output",
                "outputs",
            )
        if (
            execution_output.kind != expected_kind
            or execution_output.content_hash != content_hash
            or execution_output.codec != expected_codec
        ):
            _raise_analysis_problem(
                "analysis_output_execution_mismatch",
                "analysis output content does not match its producing execution",
                "outputs",
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

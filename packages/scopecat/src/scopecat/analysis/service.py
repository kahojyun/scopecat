"""Application use cases for authoring and persisting run analyses."""

from __future__ import annotations

import json
import mimetypes
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, NoReturn, cast

from pydantic import BaseModel, JsonValue

from scopecat.config.changes import (
    parameter_change_proposal_record_ref,
    prepare_parameter_change_proposal_contents,
)
from scopecat.kernel.content_identity import (
    content_fingerprint,
    model_wire_content_hash,
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
from scopecat.records.analysis import (
    AnalysisRecord,
    AnalysisRecordInput,
    AnalysisRecordOutput,
    AnalysisRecordOutputKind,
)
from scopecat.records.artifact import RunContentEntry
from scopecat.records.parameter_change import ParameterChangeProposal
from scopecat.runs.access import (
    artifact_storage_ref,
)
from scopecat.runs.refs import record_content_ref
from scopecat.runs.repository import (
    RunBytesWrite,
    RunContentPublication,
    RunModelWrite,
)

AnalysisOutputKind = AnalysisRecordOutputKind


@dataclass(frozen=True)
class AnalysisInput:
    target: str
    kind: Literal["artifact", "dataset", "uri"]
    role: str
    title: str | None = None
    metadata: Mapping[str, object] | None = None


@dataclass(frozen=True)
class AnalysisOutput:
    kind: AnalysisOutputKind
    title: str
    content: object
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class SavedAnalysis:
    record: RunContentEntry
    analysis_key: str
    inputs: tuple[AnalysisInput, ...] = ()
    output_artifacts: tuple[RunContentEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class PreparedAnalysis:
    saved: SavedAnalysis
    publication: RunContentPublication


@dataclass(frozen=True, slots=True)
class AnalysisArtifactSpec:
    title: str
    kind: str
    content: bytes
    artifact_id: str | None
    filename: str
    media_type: str
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class _PreparedAnalysisArtifact:
    artifact: RunContentEntry
    content: bytes


def prepare_analysis_artifact(
    *,
    title: str,
    kind: str,
    artifact_id: str | None,
    filename: str | None,
    model: BaseModel | None,
    json_content: object | None,
    text: str | None,
    content: bytes | None,
    path: str | Path | None,
    media_type: str | None,
    metadata: Mapping[str, object] | None,
) -> AnalysisArtifactSpec:
    """Validate and snapshot an artifact before its source can change."""

    if not title.strip():
        _raise_analysis_problem(
            "analysis_artifact_title_invalid",
            "analysis artifact title must be a non-empty string",
            "title",
        )
    if not kind.strip():
        _raise_analysis_problem(
            "analysis_artifact_kind_invalid",
            "analysis artifact kind must be a non-empty string",
            "kind",
        )
    selected_sources = [
        model is not None,
        json_content is not None,
        text is not None,
        content is not None,
        path is not None,
    ]
    if selected_sources.count(True) != 1:
        _raise_analysis_problem(
            "analysis_artifact_source_invalid",
            (
                "analysis artifact requires exactly one of model, json_content, "
                "text, content, or path"
            ),
            "artifact",
        )
    if artifact_id is not None and not artifact_id.strip():
        _raise_analysis_problem(
            "analysis_artifact_id_invalid",
            "analysis artifact id must be a non-empty string",
            "artifact_id",
        )
    if filename is not None and not _is_artifact_filename(filename):
        _raise_analysis_problem(
            "analysis_artifact_filename_invalid",
            f"analysis artifact filename must be a basename: {filename}",
            "filename",
        )
    source_filename: str | None = None
    if path is not None:
        source_path = Path(path)
        if not source_path.is_file():
            _raise_analysis_problem(
                "analysis_artifact_source_missing",
                f"analysis artifact source file is missing: {source_path}",
                "path",
            )
        selected_filename = filename or source_path.name
        if not _is_artifact_filename(selected_filename):
            _raise_analysis_problem(
                "analysis_artifact_filename_invalid",
                (f"analysis artifact filename must be a basename: {selected_filename}"),
                "filename",
            )
        snapshot = source_path.read_bytes()
        source_filename = source_path.name
        default_extension = ""
        default_media_type = "application/octet-stream"
    elif model is not None:
        snapshot = _text_storage_bytes(
            json.dumps(
                model.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
            )
        )
        default_extension = ".json"
        default_media_type = "application/json"
    elif json_content is not None:
        snapshot = _text_storage_bytes(
            json.dumps(
                _json_safe(json_content),
                indent=2,
                sort_keys=True,
            )
        )
        default_extension = ".json"
        default_media_type = "application/json"
    elif text is not None:
        snapshot = _text_storage_bytes(text)
        default_extension = ".txt"
        default_media_type = "text/plain"
    else:
        if content is None:
            _raise_analysis_problem(
                "analysis_artifact_source_invalid",
                (
                    "analysis artifact requires exactly one of model, json_content, "
                    "text, content, or path"
                ),
                "artifact",
            )
        snapshot = content
        default_extension = ".bin"
        default_media_type = "application/octet-stream"
    selected_filename = (
        filename
        or source_filename
        or (
            f"{artifact_slug(artifact_id or title, fallback='analysis')}"
            f"{default_extension}"
        )
    )
    guessed_media_type, _encoding = mimetypes.guess_type(selected_filename)
    return AnalysisArtifactSpec(
        title=title,
        kind=kind,
        content=snapshot,
        artifact_id=artifact_id,
        filename=selected_filename,
        media_type=media_type or guessed_media_type or default_media_type,
        metadata=metadata or {},
    )


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
    prepared_artifacts = _prepare_analysis_output_artifacts(
        analysis_key=analysis_key,
        step_id=step_id,
        analysis_record_id=selected_record_id,
        outputs=outputs,
    )
    output_artifacts = [prepared.artifact for prepared in prepared_artifacts]
    output_refs = [prepared.artifact.id for prepared in prepared_artifacts]
    analysis_record = AnalysisRecord(
        run_id=run_id,
        title=title,
        key=analysis_key,
        step_id=step_id,
        inputs=_analysis_record_inputs(inputs),
        outputs=_analysis_record_outputs(
            outputs=outputs,
            output_refs=iter(output_refs),
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
        output_artifacts=tuple(output_artifacts),
    )
    return PreparedAnalysis(
        saved=saved,
        publication=RunContentPublication(
            run_id=run_id,
            entries=(
                *prepared_proposals.entries,
                record,
                *output_artifacts,
            ),
            models=(
                *prepared_proposals.writes,
                RunModelWrite(ref=ref, value=analysis_record),
            ),
            bytes=tuple(
                RunBytesWrite(
                    ref=artifact_storage_ref(prepared.artifact),
                    content=prepared.content,
                )
                for prepared in prepared_artifacts
            ),
        ),
    )


def _saved_analysis_output_content(
    *,
    output: AnalysisOutput,
    output_refs: Iterator[str],
) -> object:
    if output.kind == "artifact":
        return {"artifact_id": next(output_refs)}
    if output.kind == "parameter_change_proposal":
        if not isinstance(output.content, ParameterChangeProposal):
            _raise_analysis_problem(
                "analysis_parameter_proposal_output_invalid",
                "analysis parameter proposal output has invalid content",
                "outputs",
            )
        return {
            "proposal_id": output.content.id,
            "record_ref": parameter_change_proposal_record_ref(output.content.id),
        }
    return output.content


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
                    _json_mapping(cast("Mapping[object, object]", metadata))
                    if metadata is not None
                    else None
                ),
            )
        )
    return record_inputs


def _analysis_record_outputs(
    *,
    outputs: Sequence[AnalysisOutput],
    output_refs: Iterator[str],
) -> list[AnalysisRecordOutput]:
    return [
        AnalysisRecordOutput(
            kind=output.kind,
            title=output.title,
            content=_json_safe(
                _saved_analysis_output_content(output=output, output_refs=output_refs)
            ),
            metadata=_json_mapping(cast("Mapping[object, object]", output.metadata)),
        )
        for output in outputs
    ]


def _prepare_analysis_output_artifacts(
    *,
    analysis_key: str,
    step_id: str | None,
    analysis_record_id: str,
    outputs: Sequence[AnalysisOutput],
) -> list[_PreparedAnalysisArtifact]:
    artifact_specs = _analysis_artifact_specs(outputs)
    if not artifact_specs:
        return []
    prepared_artifacts: list[_PreparedAnalysisArtifact] = []
    seen_artifact_ids: set[str] = set()
    default_artifact_id_counts: dict[str, int] = {}
    for spec in artifact_specs:
        selected_artifact_id = _analysis_artifact_artifact_id(
            spec,
            analysis_key=analysis_key,
            default_id_counts=default_artifact_id_counts,
            seen_artifact_ids=seen_artifact_ids,
        )
        metadata = _json_mapping(cast("Mapping[object, object]", spec.metadata))
        artifact = RunContentEntry(
            role="artifact",
            id=selected_artifact_id,
            kind=spec.kind,
            title=spec.title,
            media_type=spec.media_type,
            filename=spec.filename,
            content_hash=stable_content_hash(content_fingerprint(spec.content)),
            produced_by=(
                f"analysis_step:{step_id}"
                if step_id is not None
                else f"analysis:{analysis_record_id}"
            ),
            metadata=metadata,
        )
        prepared_artifacts.append(
            _PreparedAnalysisArtifact(
                artifact=artifact,
                content=spec.content,
            )
        )
    return prepared_artifacts


def _analysis_artifact_specs(
    outputs: Sequence[AnalysisOutput],
) -> list[AnalysisArtifactSpec]:
    specs: list[AnalysisArtifactSpec] = []
    for output in outputs:
        if output.kind != "artifact":
            continue
        if not isinstance(output.content, AnalysisArtifactSpec):
            _raise_analysis_problem(
                "analysis_artifact_output_invalid",
                "analysis artifact output has invalid content",
                "outputs",
            )
        specs.append(output.content)
    return specs


def _analysis_artifact_artifact_id(
    spec: AnalysisArtifactSpec,
    *,
    analysis_key: str,
    default_id_counts: dict[str, int],
    seen_artifact_ids: set[str],
) -> str:
    if spec.artifact_id is not None:
        if spec.artifact_id in seen_artifact_ids:
            _raise_analysis_problem(
                "analysis_artifact_id_duplicated",
                f"analysis artifact id is duplicated: {spec.artifact_id}",
                "artifact_id",
            )
        seen_artifact_ids.add(spec.artifact_id)
        return spec.artifact_id
    title_slug = artifact_slug(spec.title, fallback="analysis")
    base_id = f"analysis-{analysis_key}-{title_slug}"
    count = default_id_counts.get(base_id, 0) + 1
    default_id_counts[base_id] = count
    selected = base_id if count == 1 else f"{base_id}-{count}"
    while selected in seen_artifact_ids:
        count += 1
        default_id_counts[base_id] = count
        selected = f"{base_id}-{count}"
    seen_artifact_ids.add(selected)
    return selected


def _is_artifact_filename(filename: str) -> bool:
    if not filename or "\\" in filename:
        return False
    path = PurePosixPath(filename)
    return path.name == filename and not path.is_absolute() and ".." not in path.parts


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


def _json_safe(value: object) -> JsonValue:
    if isinstance(value, BaseModel):
        return cast("JsonValue", value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return _json_mapping(cast("Mapping[object, object]", asdict(value)))
    if isinstance(value, Mapping):
        return _json_mapping(cast("Mapping[object, object]", value))
    if isinstance(value, tuple | list):
        return [_json_safe(item) for item in cast("Sequence[object]", value)]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _json_mapping(value: Mapping[object, object]) -> dict[str, JsonValue]:
    return {str(key): _json_safe(item) for key, item in value.items()}


def _text_storage_bytes(content: str) -> bytes:
    if content and not content.endswith("\n"):
        content = f"{content}\n"
    return content.encode()

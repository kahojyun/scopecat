"""Application use cases for authoring and persisting run analyses."""

from __future__ import annotations

import json
import mimetypes
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Literal, NoReturn, Protocol, cast

from pydantic import BaseModel, JsonValue

from scopecat.application.services import WorkspaceServices
from scopecat.config.changes import (
    parameter_change_proposal_record_ref,
    write_parameter_change_proposal_contents,
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
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
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
    upsert_contents,
)
from scopecat.runs.refs import record_content_ref
from scopecat.runs.repository import RunRepository

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


class _AnalysisArtifactSource(Protocol):
    def default_filename(self) -> str | None: ...

    def default_extension(self) -> str: ...

    def default_media_type(self) -> str: ...

    def content_hash(self) -> str: ...

    def content_bytes(self) -> bytes: ...

    def write(self, *, storage: RunRepository, run_id: str, ref: str) -> None: ...


@dataclass(frozen=True)
class _AnalysisModelArtifactSource:
    model: BaseModel

    def default_filename(self) -> str | None:
        return None

    def default_extension(self) -> str:
        return ".json"

    def default_media_type(self) -> str:
        return "application/json"

    def content_hash(self) -> str:
        return model_wire_content_hash(self.model)

    def content_bytes(self) -> bytes:
        return _text_storage_bytes(
            json.dumps(
                self.model.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
            )
        )

    def write(self, *, storage: RunRepository, run_id: str, ref: str) -> None:
        storage.write_bytes(run_id, ref, self.content_bytes())


@dataclass(frozen=True)
class _AnalysisJsonArtifactSource:
    content: object

    def default_filename(self) -> str | None:
        return None

    def default_extension(self) -> str:
        return ".json"

    def default_media_type(self) -> str:
        return "application/json"

    def content_hash(self) -> str:
        return stable_content_hash(content_fingerprint(_json_safe(self.content)))

    def content_bytes(self) -> bytes:
        return _text_storage_bytes(
            json.dumps(
                _json_safe(self.content),
                indent=2,
                sort_keys=True,
            )
        )

    def write(self, *, storage: RunRepository, run_id: str, ref: str) -> None:
        storage.write_bytes(run_id, ref, self.content_bytes())


@dataclass(frozen=True)
class _AnalysisTextArtifactSource:
    content: str

    def default_filename(self) -> str | None:
        return None

    def default_extension(self) -> str:
        return ".txt"

    def default_media_type(self) -> str:
        return "text/plain"

    def content_hash(self) -> str:
        return stable_content_hash(content_fingerprint(self.content))

    def content_bytes(self) -> bytes:
        return _text_storage_bytes(self.content)

    def write(self, *, storage: RunRepository, run_id: str, ref: str) -> None:
        storage.write_bytes(run_id, ref, self.content_bytes())


@dataclass(frozen=True)
class _AnalysisBytesArtifactSource:
    content: bytes

    def default_filename(self) -> str | None:
        return None

    def default_extension(self) -> str:
        return ".bin"

    def default_media_type(self) -> str:
        return "application/octet-stream"

    def content_hash(self) -> str:
        return stable_content_hash(content_fingerprint(self.content))

    def content_bytes(self) -> bytes:
        return self.content

    def write(self, *, storage: RunRepository, run_id: str, ref: str) -> None:
        storage.write_bytes(run_id, ref, self.content_bytes())


@dataclass(frozen=True)
class _AnalysisFileArtifactSource:
    path: Path

    def default_filename(self) -> str | None:
        return self.path.name

    def default_extension(self) -> str:
        return ""

    def default_media_type(self) -> str:
        return "application/octet-stream"

    def content_hash(self) -> str:
        return stable_content_hash(content_fingerprint(self.path.read_bytes()))

    def content_bytes(self) -> bytes:
        return self.path.read_bytes()

    def write(self, *, storage: RunRepository, run_id: str, ref: str) -> None:
        storage.write_bytes(run_id, ref, self.content_bytes())


@dataclass(frozen=True)
class _EncodedAnalysisArtifactSource:
    content: bytes
    filename: str | None
    extension: str
    media_type: str
    declared_content_hash: str | None

    def default_filename(self) -> str | None:
        return self.filename

    def default_extension(self) -> str:
        return self.extension

    def default_media_type(self) -> str:
        return self.media_type

    def content_hash(self) -> str:
        return self.declared_content_hash or stable_content_hash(
            content_fingerprint(self.content)
        )

    def content_bytes(self) -> bytes:
        return self.content

    def write(self, *, storage: RunRepository, run_id: str, ref: str) -> None:
        storage.write_bytes(run_id, ref, self.content)


@dataclass(frozen=True)
class AnalysisArtifactSpec:
    title: str
    kind: str
    source: _AnalysisArtifactSource
    artifact_id: str | None
    filename: str | None
    media_type: str | None
    metadata: Mapping[str, object]

    def content_bytes(self) -> bytes:
        return self.source.content_bytes()

    def source_default_filename(self) -> str | None:
        return self.source.default_filename()

    def source_default_extension(self) -> str:
        return self.source.default_extension()

    def source_default_media_type(self) -> str:
        return self.source.default_media_type()

    def source_content_hash(self) -> str:
        return self.source.content_hash()


@dataclass(frozen=True)
class _PreparedAnalysisArtifact:
    spec: AnalysisArtifactSpec
    artifact: RunContentEntry
    artifact_id: str


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
    """Validate an artifact request and bind its source for later ingestion."""

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
    source: _AnalysisArtifactSource
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
        source = _AnalysisFileArtifactSource(path=source_path)
    elif model is not None:
        source = _AnalysisModelArtifactSource(model=model)
    elif json_content is not None:
        source = _AnalysisJsonArtifactSource(content=json_content)
    elif text is not None:
        source = _AnalysisTextArtifactSource(content=text)
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
        source = _AnalysisBytesArtifactSource(content=content)
    return AnalysisArtifactSpec(
        title=title,
        kind=kind,
        source=source,
        artifact_id=artifact_id,
        filename=filename,
        media_type=media_type,
        metadata=metadata or {},
    )


def prepare_encoded_analysis_artifact(
    *,
    title: str,
    kind: str,
    artifact_id: str | None,
    filename: str | None,
    content: bytes,
    media_type: str | None,
    metadata: Mapping[str, object] | None,
    source_default_filename: str | None,
    source_default_extension: str,
    source_default_media_type: str,
    source_content_hash: str | None,
) -> AnalysisArtifactSpec:
    """Rebuild a client-prepared artifact without losing its source defaults."""

    spec = prepare_analysis_artifact(
        title=title,
        kind=kind,
        artifact_id=artifact_id,
        filename=filename,
        model=None,
        json_content=None,
        text=None,
        content=content,
        path=None,
        media_type=media_type,
        metadata=metadata,
    )
    return replace(
        spec,
        source=_EncodedAnalysisArtifactSource(
            content=content,
            filename=source_default_filename,
            extension=source_default_extension,
            media_type=source_default_media_type,
            declared_content_hash=source_content_hash,
        ),
    )


def save_analysis(
    *,
    services: WorkspaceServices,
    run_id: str,
    title: str,
    analysis_key: str,
    step_id: str | None,
    inputs: Sequence[AnalysisInput],
    outputs: Sequence[AnalysisOutput],
    parameter_proposals: Sequence[ParameterChangeProposal],
) -> SavedAnalysis:
    """Persist one analysis record and its owned durable evidence."""

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
    output_refs = [prepared.artifact_id for prepared in prepared_artifacts]
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
    manifest = storage.read_manifest(run_id)
    proposal_records = write_parameter_change_proposal_contents(
        storage=storage,
        run_id=run_id,
        proposals=parameter_proposals,
    )
    _write_prepared_analysis_output_artifacts(
        storage=storage,
        run_id=run_id,
        prepared_artifacts=prepared_artifacts,
    )
    storage.write_model(run_id, ref, analysis_record)

    # The manifest commits newly published content above. A failure before
    # this write leaves retryable, uncommitted content.
    updated_manifest = manifest.model_copy(
        update={
            "contents": upsert_contents(
                manifest.contents,
                (*proposal_records, record, *output_artifacts),
            ),
        }
    )
    storage.write_manifest(updated_manifest)
    return SavedAnalysis(
        record=record,
        analysis_key=analysis_key,
        inputs=tuple(inputs),
        output_artifacts=tuple(output_artifacts),
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
        selected_filename = _analysis_artifact_filename(spec, selected_artifact_id)
        media_type = _analysis_artifact_media_type(spec, selected_filename)
        metadata = _json_mapping(cast("Mapping[object, object]", spec.metadata))
        artifact = RunContentEntry(
            role="artifact",
            id=selected_artifact_id,
            kind=spec.kind,
            title=spec.title,
            media_type=media_type,
            filename=selected_filename,
            content_hash=spec.source.content_hash(),
            produced_by=(
                f"analysis_step:{step_id}"
                if step_id is not None
                else f"analysis:{analysis_record_id}"
            ),
            metadata=metadata,
        )
        prepared_artifacts.append(
            _PreparedAnalysisArtifact(
                spec=spec,
                artifact=artifact,
                artifact_id=selected_artifact_id,
            )
        )
    return prepared_artifacts


def _write_prepared_analysis_output_artifacts(
    *,
    storage: RunRepository,
    run_id: str,
    prepared_artifacts: Sequence[_PreparedAnalysisArtifact],
) -> None:
    for prepared in prepared_artifacts:
        prepared.spec.source.write(
            storage=storage,
            run_id=run_id,
            ref=artifact_storage_ref(prepared.artifact),
        )


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


def _analysis_artifact_filename(
    spec: AnalysisArtifactSpec,
    selected_artifact_id: str,
) -> str:
    if spec.filename is not None:
        return spec.filename
    source_filename = spec.source.default_filename()
    if source_filename is not None:
        return source_filename
    extension = spec.source.default_extension()
    return f"{artifact_slug(selected_artifact_id, fallback='analysis')}{extension}"


def _analysis_artifact_media_type(
    spec: AnalysisArtifactSpec,
    filename: str,
) -> str:
    if spec.media_type is not None:
        return spec.media_type
    guessed, _encoding = mimetypes.guess_type(filename)
    if guessed is not None:
        return guessed
    return spec.source.default_media_type()


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
            blocking_problem(
                code,
                message,
                category=ProblemCategory.INVALID_INPUT,
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

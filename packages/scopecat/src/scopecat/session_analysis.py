"""Analysis facade objects for notebook workflows."""

from __future__ import annotations

import json
import mimetypes
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal, NoReturn, Protocol, cast

from pydantic import BaseModel

from scopecat._manifest_updates import write_manifest_artifacts
from scopecat.candidate_configs import (
    CandidateConfig,
    CandidateSelection,
)
from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.ids import artifact_slug
from scopecat.models.artifact import Artifact
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import ParameterChangeSet
from scopecat.parameter_changes import (
    AnalysisParameterPatch,
    parameter_change_set_from_analysis_patches,
)
from scopecat.runs.access import RunStore, open_run_store
from scopecat.session_data import Data

if TYPE_CHECKING:
    from scopecat.session_run_handle import RunHandle


AnalysisOutputKind = Literal[
    "note",
    "table",
    "array",
    "figure",
    "artifact",
    "parameter_change",
]


@dataclass(frozen=True)
class AnalysisArtifactRef:
    target: str
    target_type: Literal["artifact"]
    artifact_kind: str | None = None
    path: str | None = None
    media_type: str | None = None


@dataclass(frozen=True)
class AnalysisInputRef:
    target: str
    target_type: Literal["artifact", "uri"]
    role: str
    title: str | None = None
    artifact_kind: str | None = None
    path: str | None = None
    media_type: str | None = None
    metadata: Mapping[str, object] | None = None


@dataclass(frozen=True)
class _AnalysisArtifactSpec:
    title: str
    kind: str
    source_kind: Literal["model", "json", "text", "bytes", "path"]
    source_path: Path | None
    model: BaseModel | None
    json_content: object | None
    text: str | None
    content: bytes | None
    artifact_id: str | None
    filename: str | None
    media_type: str | None
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class _PreparedAnalysisArtifact:
    spec: _AnalysisArtifactSpec
    artifact: Artifact
    ref: AnalysisArtifactRef


@dataclass(frozen=True)
class AnalysisOutput:
    kind: AnalysisOutputKind
    title: str
    content: object
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class SavedAnalysis:
    artifact: Artifact
    path: str
    analysis_key: str
    inputs: tuple[AnalysisInputRef, ...] = ()
    source_artifact_ids: tuple[str, ...] = ()
    output_artifacts: tuple[Artifact, ...] = ()


@dataclass(frozen=True)
class Analysis:
    """In-notebook analysis record for exploratory experiment work."""

    run: RunHandle
    title: str
    key: str | None = None
    step_id: str | None = None
    inputs: tuple[AnalysisInputRef, ...] = ()
    outputs: tuple[AnalysisOutput, ...] = ()
    parameter_changes: tuple[ParameterChangeSet, ...] = ()

    def note(
        self,
        content: str,
        *,
        title: str = "note",
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis:
        if not content.strip():
            _raise_analysis_diagnostic(
                "analysis_note_invalid",
                "analysis note content must be a non-empty string",
                "content",
            )
        return self._with_output("note", title, content, metadata)

    def table(
        self,
        content: object,
        *,
        title: str = "table",
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis:
        return self._with_output("table", title, content, metadata)

    def array(
        self,
        content: object,
        *,
        title: str = "array",
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis:
        return self._with_output("array", title, content, metadata)

    def figure(
        self,
        content: object,
        *,
        title: str = "figure",
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis:
        return self._with_output("figure", title, content, metadata)

    @property
    def analysis_key(self) -> str:
        return _analysis_key(self.key, self.title)

    def input(
        self,
        selector: str | None = None,
        *,
        uri: str | None = None,
        role: str = "data",
        title: str | None = None,
        expected_kind: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis:
        if not role.strip():
            _raise_analysis_diagnostic(
                "analysis_input_role_invalid",
                "analysis input role must be a non-empty string",
                "role",
            )
        selected_sources = [selector is not None, uri is not None].count(True)
        if selected_sources != 1:
            _raise_analysis_diagnostic(
                "analysis_input_source_invalid",
                "analysis input requires exactly one of selector or uri",
                "input",
            )
        if uri is not None:
            if not uri.strip():
                _raise_analysis_diagnostic(
                    "analysis_input_uri_invalid",
                    "analysis input URI must be non-empty",
                    "uri",
                )
            ref = AnalysisInputRef(
                target=uri,
                target_type="uri",
                role=role,
                title=title,
                metadata=metadata,
            )
            return replace(self, inputs=(*self.inputs, ref))
        assert selector is not None
        artifact = self.run.data().artifact(selector, expected_kind=expected_kind)
        ref = AnalysisInputRef(
            target=artifact.id,
            target_type="artifact",
            role=role,
            title=title or artifact.id,
            artifact_kind=artifact.kind,
            path=artifact.path,
            media_type=artifact.media_type,
            metadata=metadata,
        )
        return replace(self, inputs=(*self.inputs, ref))

    def artifact(
        self,
        *,
        title: str,
        kind: str,
        artifact_id: str | None = None,
        filename: str | None = None,
        model: BaseModel | None = None,
        json_content: object | None = None,
        text: str | None = None,
        content: bytes | None = None,
        path: str | Path | None = None,
        media_type: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis:
        if not title.strip():
            _raise_analysis_diagnostic(
                "analysis_artifact_title_invalid",
                "analysis artifact title must be a non-empty string",
                "title",
            )
        if not kind.strip():
            _raise_analysis_diagnostic(
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
            _raise_analysis_diagnostic(
                "analysis_artifact_source_invalid",
                (
                    "analysis artifact requires exactly one of model, json_content, "
                    "text, content, or path"
                ),
                "artifact",
            )
        if artifact_id is not None and not artifact_id.strip():
            _raise_analysis_diagnostic(
                "analysis_artifact_id_invalid",
                "analysis artifact id must be a non-empty string",
                "artifact_id",
            )
        if filename is not None and not _is_artifact_filename(filename):
            _raise_analysis_diagnostic(
                "analysis_artifact_filename_invalid",
                f"analysis artifact filename must be a basename: {filename}",
                "filename",
            )
        source_path: Path | None = None
        source_kind: Literal["model", "json", "text", "bytes", "path"]
        if path is not None:
            source_kind = "path"
            source_path = Path(path)
            if not source_path.is_file():
                _raise_analysis_diagnostic(
                    "analysis_artifact_source_missing",
                    f"analysis artifact source file is missing: {source_path}",
                    "path",
                )
            selected_filename = filename or source_path.name
            if not _is_artifact_filename(selected_filename):
                _raise_analysis_diagnostic(
                    "analysis_artifact_filename_invalid",
                    (
                        "analysis artifact filename must be a basename: "
                        f"{selected_filename}"
                    ),
                    "filename",
                )
        elif model is not None:
            source_kind = "model"
        elif json_content is not None:
            source_kind = "json"
        elif text is not None:
            source_kind = "text"
        else:
            source_kind = "bytes"
        artifact_spec = _AnalysisArtifactSpec(
            title=title,
            kind=kind,
            source_kind=source_kind,
            source_path=source_path,
            model=model,
            json_content=json_content,
            text=text,
            content=content,
            artifact_id=artifact_id,
            filename=filename,
            media_type=media_type,
            metadata=metadata or {},
        )
        return self._with_output("artifact", title, artifact_spec, {})

    def propose(
        self,
        change_id: str,
        *patches: AnalysisParameterPatch,
        reason: str = "",
        confidence: float | None = None,
    ) -> Analysis:
        if not change_id.strip():
            _raise_analysis_diagnostic(
                "analysis_parameter_change_id_invalid",
                "analysis parameter change id must be non-empty",
                "change_id",
            )
        if not patches:
            _raise_analysis_diagnostic(
                "analysis_parameter_change_empty",
                "analysis parameter change requires at least one patch",
                "patches",
            )
        if confidence is not None and not 0 <= confidence <= 1:
            _raise_analysis_diagnostic(
                "analysis_parameter_change_confidence_invalid",
                "analysis parameter change confidence must be between 0 and 1",
                "confidence",
            )
        selected_id = artifact_slug(change_id, fallback="analysis")
        if any(change.id == selected_id for change in self.parameter_changes):
            _raise_analysis_diagnostic(
                "analysis_parameter_change_id_duplicated",
                f"analysis parameter change id is duplicated: {selected_id}",
                "change_id",
            )
        try:
            change = parameter_change_set_from_analysis_patches(
                source_run_id=self.run.id,
                analysis_title=self.title,
                change_id=change_id,
                patches=patches,
                reason=reason,
                confidence=confidence,
            )
        except (TypeError, ValueError) as error:
            _raise_analysis_diagnostic(
                "analysis_parameter_change_invalid",
                str(error),
                "patches",
            )
        output = AnalysisOutput(
            kind="parameter_change",
            title=selected_id,
            content=change,
            metadata={},
        )
        return replace(
            self,
            outputs=(*self.outputs, output),
            parameter_changes=(*self.parameter_changes, change),
        )

    def candidate_config(
        self,
        selection: CandidateSelection = None,
    ) -> CandidateConfig:
        changes = _select_candidate_changes(
            self.parameter_changes,
            selection=selection,
        )
        return CandidateConfig(
            analysis_title=self.title,
            analysis_key=self.analysis_key,
            changes=changes,
        )

    def promote_step(self, step_id: str) -> PromotedAnalysisStep:
        return PromotedAnalysisStep(id=step_id, source=self)

    def save(self) -> SavedAnalysis:
        analysis_key = self.analysis_key
        selected_artifact_id = f"analysis-{analysis_key}"
        ref = f"artifacts/{selected_artifact_id}.json"
        source_artifact_ids = _analysis_source_artifact_ids(self.inputs)
        storage = open_run_store(self.run.session.workspace)
        output_artifacts, output_refs = _write_analysis_output_artifacts(
            storage=storage,
            run_id=self.run.id,
            analysis_title=self.title,
            analysis_key=analysis_key,
            step_id=self.step_id,
            analysis_artifact_id=selected_artifact_id,
            outputs=self.outputs,
            inputs=self.inputs,
            source_artifact_ids=source_artifact_ids,
        )
        output_ref_iter = iter(output_refs)
        content = {
            "schema_version": "scopecat.analysis.v2",
            "run_id": self.run.id,
            "title": self.title,
            "key": analysis_key,
            "step_id": self.step_id,
            "inputs": [_json_safe(input_ref) for input_ref in self.inputs],
            "source_artifact_ids": list(source_artifact_ids),
            "outputs": [
                {
                    "kind": output.kind,
                    "title": output.title,
                    "content": _json_safe(
                        _saved_analysis_output_content(
                            output=output,
                            output_refs=output_ref_iter,
                        )
                    ),
                    "metadata": _json_safe(output.metadata),
                }
                for output in self.outputs
            ],
            "parameter_changes": [
                _json_safe(change) for change in self.parameter_changes
            ],
        }
        storage.write_text(
            self.run.id,
            ref,
            json.dumps(content, indent=2, sort_keys=True),
        )
        artifact = Artifact(
            id=selected_artifact_id,
            kind="analysis",
            path=ref,
            media_type="application/json",
            metadata={
                "analysis_title": self.title,
                "analysis_key": analysis_key,
                "owner_type": "analysis",
                "owner_key": analysis_key,
                "step_id": self.step_id,
                "output_kinds": [output.kind for output in self.outputs],
                "parameter_change_count": len(self.parameter_changes),
                "source_run_id": self.run.id,
                "inputs": [_json_safe(input_ref) for input_ref in self.inputs],
                "source_artifact_ids": list(source_artifact_ids),
            },
        )
        write_manifest_artifacts(
            storage=storage,
            manifest=storage.read_manifest(self.run.id),
            artifacts=[artifact, *output_artifacts],
        )
        return SavedAnalysis(
            artifact=artifact,
            path=ref,
            analysis_key=analysis_key,
            inputs=self.inputs,
            source_artifact_ids=source_artifact_ids,
            output_artifacts=tuple(output_artifacts),
        )

    def _with_output(
        self,
        kind: AnalysisOutputKind,
        title: str,
        content: object,
        metadata: Mapping[str, object] | None,
    ) -> Analysis:
        return replace(
            self,
            outputs=(
                *self.outputs,
                AnalysisOutput(
                    kind=kind,
                    title=title,
                    content=content,
                    metadata=metadata or {},
                ),
            ),
        )


@dataclass(frozen=True)
class AnalysisContext:
    run: RunHandle
    data: Data
    default_key: str | None = None
    step_id: str | None = None

    @property
    def config(self) -> ConfigProfileSnapshot:
        return self.run.config

    def result(self, title: str = "analysis", *, key: str | None = None) -> Analysis:
        return self.run.analysis(
            title,
            key=key or self.default_key,
            step_id=self.step_id,
        )


class AnalysisStep(Protocol):
    id: str

    def run(self, context: AnalysisContext) -> Analysis: ...


@dataclass(frozen=True)
class PromotedAnalysisStep:
    id: str
    source: Analysis

    def run(self, run: RunHandle) -> Analysis:
        return Analysis(
            run=run,
            title=self.source.title,
            key=self.id,
            step_id=self.id,
            inputs=self.source.inputs,
            outputs=self.source.outputs,
            parameter_changes=self.source.parameter_changes,
        )


def _select_candidate_changes(
    changes: Sequence[ParameterChangeSet],
    *,
    selection: CandidateSelection,
) -> tuple[ParameterChangeSet, ...]:
    if not changes:
        _raise_analysis_diagnostic(
            "candidate_config_no_parameter_changes",
            "candidate config requires at least one parameter change",
            "parameter_changes",
        )
    if selection is None:
        if len(changes) == 1:
            return (changes[0],)
        _raise_analysis_diagnostic(
            "candidate_config_selection_required",
            (
                "candidate config selection is required when analysis has multiple "
                "parameter changes"
            ),
            "selection",
        )
    selected_ids = (selection,) if isinstance(selection, str) else tuple(selection)
    if not selected_ids:
        _raise_analysis_diagnostic(
            "candidate_config_selection_empty",
            "candidate config selection must include at least one parameter change",
            "selection",
        )
    by_id = {change.id: change for change in changes}
    selected: list[ParameterChangeSet] = []
    seen: set[str] = set()
    for selected_id in selected_ids:
        change_id = artifact_slug(selected_id, fallback="analysis")
        if change_id in seen:
            _raise_analysis_diagnostic(
                "candidate_config_selection_duplicated",
                f"candidate config selection is duplicated: {change_id}",
                "selection",
            )
        try:
            selected.append(by_id[change_id])
        except KeyError:
            _raise_analysis_diagnostic(
                "candidate_config_selection_not_found",
                f"candidate config selection was not found: {change_id}",
                "selection",
            )
        seen.add(change_id)
    return tuple(selected)


def _analysis_source_artifact_ids(
    inputs: Sequence[AnalysisInputRef],
) -> tuple[str, ...]:
    artifact_ids: list[str] = []
    seen: set[str] = set()
    for input_ref in inputs:
        if input_ref.target_type != "artifact":
            continue
        artifact_id = input_ref.target
        if artifact_id in seen:
            continue
        artifact_ids.append(artifact_id)
        seen.add(artifact_id)
    return tuple(artifact_ids)


def _saved_analysis_output_content(
    *,
    output: AnalysisOutput,
    output_refs: Iterator[AnalysisArtifactRef],
) -> object:
    if output.kind == "artifact":
        return next(output_refs)
    return output.content


def _write_analysis_output_artifacts(
    *,
    storage: RunStore,
    run_id: str,
    analysis_title: str,
    analysis_key: str,
    step_id: str | None,
    analysis_artifact_id: str,
    outputs: Sequence[AnalysisOutput],
    inputs: Sequence[AnalysisInputRef],
    source_artifact_ids: Sequence[str],
) -> tuple[
    list[Artifact],
    list[AnalysisArtifactRef],
]:
    artifact_specs = _analysis_artifact_specs(outputs)
    if not artifact_specs:
        return [], []
    prepared_artifacts: list[_PreparedAnalysisArtifact] = []
    seen_artifact_ids = {analysis_artifact_id}
    seen_filenames = {f"{analysis_artifact_id}.json"}
    default_artifact_id_counts: dict[str, int] = {}
    for spec in artifact_specs:
        selected_artifact_id = _analysis_artifact_artifact_id(
            spec,
            analysis_key=analysis_key,
            default_id_counts=default_artifact_id_counts,
            seen_artifact_ids=seen_artifact_ids,
        )
        selected_filename = _analysis_artifact_filename(spec, selected_artifact_id)
        if selected_filename in seen_filenames:
            _raise_analysis_diagnostic(
                "analysis_artifact_filename_duplicated",
                f"analysis artifact filename is duplicated: {selected_filename}",
                "filename",
            )
        seen_filenames.add(selected_filename)
        ref = f"artifacts/{selected_filename}"
        media_type = _analysis_artifact_media_type(spec, selected_filename)
        metadata = _json_mapping(cast("Mapping[object, object]", spec.metadata))
        metadata.update(
            {
                "analysis_title": analysis_title,
                "analysis_key": analysis_key,
                "owner_type": "analysis",
                "owner_key": analysis_key,
                "step_id": step_id,
                "source_run_id": run_id,
                "source_analysis_artifact_id": analysis_artifact_id,
                "artifact_title": spec.title,
                "inputs": [_json_safe(input_ref) for input_ref in inputs],
                "source_artifact_ids": list(source_artifact_ids),
            }
        )
        artifact = Artifact(
            id=selected_artifact_id,
            kind=spec.kind,
            path=ref,
            media_type=media_type,
            metadata=metadata,
        )
        artifact_ref = AnalysisArtifactRef(
            target=selected_artifact_id,
            target_type="artifact",
            artifact_kind=spec.kind,
            path=ref,
            media_type=media_type,
        )
        prepared_artifacts.append(
            _PreparedAnalysisArtifact(
                spec=spec,
                artifact=artifact,
                ref=artifact_ref,
            )
        )
    for prepared in prepared_artifacts:
        _write_analysis_artifact_content(
            storage=storage,
            run_id=run_id,
            ref=prepared.artifact.path,
            spec=prepared.spec,
        )
    return (
        [prepared.artifact for prepared in prepared_artifacts],
        [prepared.ref for prepared in prepared_artifacts],
    )


def _analysis_artifact_specs(
    outputs: Sequence[AnalysisOutput],
) -> list[_AnalysisArtifactSpec]:
    specs: list[_AnalysisArtifactSpec] = []
    for output in outputs:
        if output.kind != "artifact":
            continue
        if not isinstance(output.content, _AnalysisArtifactSpec):
            _raise_analysis_diagnostic(
                "analysis_artifact_output_invalid",
                "analysis artifact output has invalid content",
                "outputs",
            )
        specs.append(output.content)
    return specs


def _analysis_artifact_artifact_id(
    spec: _AnalysisArtifactSpec,
    *,
    analysis_key: str,
    default_id_counts: dict[str, int],
    seen_artifact_ids: set[str],
) -> str:
    if spec.artifact_id is not None:
        if spec.artifact_id in seen_artifact_ids:
            _raise_analysis_diagnostic(
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
    spec: _AnalysisArtifactSpec,
    selected_artifact_id: str,
) -> str:
    if spec.filename is not None:
        return spec.filename
    if spec.source_path is not None:
        return spec.source_path.name
    extension = {
        "model": ".json",
        "json": ".json",
        "text": ".txt",
        "bytes": ".bin",
        "path": "",
    }[spec.source_kind]
    return f"{artifact_slug(selected_artifact_id, fallback='analysis')}{extension}"


def _analysis_artifact_media_type(
    spec: _AnalysisArtifactSpec,
    filename: str,
) -> str:
    if spec.media_type is not None:
        return spec.media_type
    guessed, _encoding = mimetypes.guess_type(filename)
    if guessed is not None:
        return guessed
    if spec.source_kind in {"model", "json"}:
        return "application/json"
    if spec.source_kind == "text":
        return "text/plain"
    return "application/octet-stream"


def _write_analysis_artifact_content(
    *,
    storage: RunStore,
    run_id: str,
    ref: str,
    spec: _AnalysisArtifactSpec,
) -> None:
    if spec.source_path is not None:
        _write_run_bytes(storage, run_id, ref, spec.source_path.read_bytes())
        return
    if spec.model is not None:
        storage.write_text(
            run_id,
            ref,
            json.dumps(spec.model.model_dump(mode="json"), indent=2, sort_keys=True),
        )
        return
    if spec.json_content is not None:
        storage.write_text(
            run_id,
            ref,
            json.dumps(_json_safe(spec.json_content), indent=2, sort_keys=True),
        )
        return
    if spec.text is not None:
        storage.write_text(run_id, ref, spec.text)
        return
    if spec.content is not None:
        _write_run_bytes(storage, run_id, ref, spec.content)
        return
    _raise_analysis_diagnostic(
        "analysis_artifact_source_invalid",
        (
            "analysis artifact requires exactly one of model, json_content, "
            "text, content, or path"
        ),
        "artifact",
    )


def _write_run_bytes(
    storage: RunStore,
    run_id: str,
    ref: str,
    content: bytes,
) -> None:
    path = storage.ref_path(run_id, ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _is_artifact_filename(filename: str) -> bool:
    if not filename or "\\" in filename:
        return False
    path = PurePosixPath(filename)
    return path.name == filename and not path.is_absolute() and ".." not in path.parts


def _analysis_key(key: str | None, title: str) -> str:
    selected = key if key is not None else title
    if not selected.strip():
        _raise_analysis_diagnostic(
            "analysis_key_invalid",
            "analysis key must be a non-empty string",
            "key",
        )
    return artifact_slug(selected, fallback="analysis")


def _raise_analysis_diagnostic(code: str, message: str, path: str) -> NoReturn:
    raise ValidationFailed(
        [
            Diagnostic(
                severity="error",
                code=code,
                message=message,
                path=path,
            )
        ]
    )


def _json_safe(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return _json_mapping(cast("Mapping[object, object]", asdict(value)))
    if isinstance(value, Mapping):
        return _json_mapping(cast("Mapping[object, object]", value))
    if isinstance(value, tuple | list):
        return [_json_safe(item) for item in cast("Sequence[object]", value)]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _json_mapping(value: Mapping[object, object]) -> dict[str, object]:
    return {str(key): _json_safe(item) for key, item in value.items()}


__all__ = [
    "Analysis",
    "AnalysisArtifactRef",
    "AnalysisContext",
    "AnalysisInputRef",
    "AnalysisOutput",
    "AnalysisStep",
    "PromotedAnalysisStep",
    "SavedAnalysis",
]

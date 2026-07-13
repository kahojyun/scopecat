"""Analysis facade objects for notebook workflows."""

from __future__ import annotations

import json
import mimetypes
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal, NoReturn, Protocol, cast

from pydantic import BaseModel

from scopecat._manifest_updates import write_manifest_artifacts, write_manifest_records
from scopecat._parameter_updates import ParameterUpdate
from scopecat._storage.local.io import ensure_durable_directory
from scopecat._storage.refs import record_content_ref
from scopecat.candidate_configs import (
    CandidateConfig,
    CandidateSelection,
)
from scopecat.errors import CheckFailed
from scopecat.ids import artifact_slug
from scopecat.models.analysis import (
    AnalysisRecord,
    AnalysisRecordInput,
    AnalysisRecordOutput,
    AnalysisRecordOutputKind,
)
from scopecat.models.artifact import RunArtifactEntry, RunRecordEntry
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter_change import ParameterChangeProposal
from scopecat.parameter_changes import (
    parameter_change_proposal_from_updates,
    parameter_change_proposal_record_ref,
    write_parameter_change_proposals,
)
from scopecat.problems import (
    LocationPathItem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.runs.access import RunStore, artifact_storage_ref, open_run_store
from scopecat.session_data import Data

if TYPE_CHECKING:
    from scopecat.session_run_handle import RunHandle


AnalysisOutputKind = AnalysisRecordOutputKind


@dataclass(frozen=True)
class AnalysisInput:
    target: str
    kind: Literal["artifact", "dataset", "uri"]
    role: str
    title: str | None = None
    metadata: Mapping[str, object] | None = None


class _AnalysisArtifactSource(Protocol):
    def default_filename(self) -> str | None: ...

    def default_extension(self) -> str: ...

    def default_media_type(self) -> str: ...

    def write(self, *, storage: RunStore, run_id: str, ref: str) -> None: ...


@dataclass(frozen=True)
class _AnalysisModelArtifactSource:
    model: BaseModel

    def default_filename(self) -> str | None:
        return None

    def default_extension(self) -> str:
        return ".json"

    def default_media_type(self) -> str:
        return "application/json"

    def write(self, *, storage: RunStore, run_id: str, ref: str) -> None:
        storage.write_text(
            run_id,
            ref,
            json.dumps(self.model.model_dump(mode="json"), indent=2, sort_keys=True),
        )


@dataclass(frozen=True)
class _AnalysisJsonArtifactSource:
    content: object

    def default_filename(self) -> str | None:
        return None

    def default_extension(self) -> str:
        return ".json"

    def default_media_type(self) -> str:
        return "application/json"

    def write(self, *, storage: RunStore, run_id: str, ref: str) -> None:
        storage.write_text(
            run_id,
            ref,
            json.dumps(_json_safe(self.content), indent=2, sort_keys=True),
        )


@dataclass(frozen=True)
class _AnalysisTextArtifactSource:
    content: str

    def default_filename(self) -> str | None:
        return None

    def default_extension(self) -> str:
        return ".txt"

    def default_media_type(self) -> str:
        return "text/plain"

    def write(self, *, storage: RunStore, run_id: str, ref: str) -> None:
        storage.write_text(run_id, ref, self.content)


@dataclass(frozen=True)
class _AnalysisBytesArtifactSource:
    content: bytes

    def default_filename(self) -> str | None:
        return None

    def default_extension(self) -> str:
        return ".bin"

    def default_media_type(self) -> str:
        return "application/octet-stream"

    def write(self, *, storage: RunStore, run_id: str, ref: str) -> None:
        _write_run_bytes(storage, run_id, ref, self.content)


@dataclass(frozen=True)
class _AnalysisFileArtifactSource:
    path: Path

    def default_filename(self) -> str | None:
        return self.path.name

    def default_extension(self) -> str:
        return ""

    def default_media_type(self) -> str:
        return "application/octet-stream"

    def write(self, *, storage: RunStore, run_id: str, ref: str) -> None:
        _write_run_bytes(storage, run_id, ref, self.path.read_bytes())


@dataclass(frozen=True)
class _AnalysisArtifactSpec:
    title: str
    kind: str
    source: _AnalysisArtifactSource
    artifact_id: str | None
    filename: str | None
    media_type: str | None
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class _PreparedAnalysisArtifact:
    spec: _AnalysisArtifactSpec
    artifact: RunArtifactEntry
    artifact_id: str


@dataclass(frozen=True)
class AnalysisOutput:
    kind: AnalysisOutputKind
    title: str
    content: object
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class SavedAnalysis:
    record: RunRecordEntry
    analysis_key: str
    inputs: tuple[AnalysisInput, ...] = ()
    output_artifacts: tuple[RunArtifactEntry, ...] = ()


@dataclass(frozen=True)
class Analysis:
    """In-notebook analysis record for exploratory experiment work."""

    run: RunHandle
    title: str
    key: str | None = None
    step_id: str | None = None
    inputs: tuple[AnalysisInput, ...] = ()
    outputs: tuple[AnalysisOutput, ...] = ()
    parameter_proposals: tuple[ParameterChangeProposal, ...] = ()

    def note(
        self,
        content: str,
        *,
        title: str = "note",
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis:
        if not content.strip():
            _raise_analysis_problem(
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
            _raise_analysis_problem(
                "analysis_input_role_invalid",
                "analysis input role must be a non-empty string",
                "role",
            )
        selected_sources = [selector is not None, uri is not None].count(True)
        if selected_sources != 1:
            _raise_analysis_problem(
                "analysis_input_source_invalid",
                "analysis input requires exactly one of selector or uri",
                "input",
            )
        if uri is not None:
            if not uri.strip():
                _raise_analysis_problem(
                    "analysis_input_uri_invalid",
                    "analysis input URI must be non-empty",
                    "uri",
                )
            analysis_input = AnalysisInput(
                target=uri,
                kind="uri",
                role=role,
                title=title,
                metadata=metadata,
            )
            return replace(self, inputs=(*self.inputs, analysis_input))
        assert selector is not None
        if expected_kind in {"measurement_dataset", "data_table", "data_array"}:
            dataset = self.run.data().dataset(selector, expected_kind=expected_kind)
            analysis_input = AnalysisInput(
                target=dataset.id,
                kind="dataset",
                role=role,
                title=title or dataset.id,
                metadata=metadata,
            )
        else:
            artifact = self.run.data().artifact(selector, expected_kind=expected_kind)
            analysis_input = AnalysisInput(
                target=artifact.id,
                kind="artifact",
                role=role,
                title=title or artifact.id,
                metadata=metadata,
            )
        return replace(self, inputs=(*self.inputs, analysis_input))

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
                    (
                        "analysis artifact filename must be a basename: "
                        f"{selected_filename}"
                    ),
                    "filename",
                )
            source: _AnalysisArtifactSource = _AnalysisFileArtifactSource(
                path=source_path,
            )
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
                        "analysis artifact requires exactly one of model, "
                        "json_content, text, content, or path"
                    ),
                    "artifact",
                )
            source = _AnalysisBytesArtifactSource(content=content)
        artifact_spec = _AnalysisArtifactSpec(
            title=title,
            kind=kind,
            source=source,
            artifact_id=artifact_id,
            filename=filename,
            media_type=media_type,
            metadata=metadata or {},
        )
        return self._with_output("artifact", title, artifact_spec, {})

    def propose(
        self,
        proposal_id: str,
        *updates: ParameterUpdate,
        reason: str = "",
        confidence: float | None = None,
    ) -> Analysis:
        if not proposal_id.strip():
            _raise_analysis_problem(
                "analysis_parameter_proposal_id_invalid",
                "analysis parameter proposal id must be non-empty",
                "proposal_id",
            )
        if not updates:
            _raise_analysis_problem(
                "analysis_parameter_proposal_empty",
                "analysis parameter proposal requires at least one update",
                "updates",
            )
        if confidence is not None and not 0 <= confidence <= 1:
            _raise_analysis_problem(
                "analysis_parameter_proposal_confidence_invalid",
                "analysis parameter proposal confidence must be between 0 and 1",
                "confidence",
            )
        selected_id = artifact_slug(proposal_id, fallback="analysis")
        if any(proposal.id == selected_id for proposal in self.parameter_proposals):
            _raise_analysis_problem(
                "analysis_parameter_proposal_id_duplicated",
                f"analysis parameter proposal id is duplicated: {selected_id}",
                "proposal_id",
            )
        try:
            proposal = parameter_change_proposal_from_updates(
                source_run_id=self.run.id,
                source_config=self.run.config,
                analysis_title=self.title,
                proposal_id=proposal_id,
                updates=updates,
                reason=reason,
                confidence=confidence,
            )
        except (TypeError, ValueError) as error:
            _raise_analysis_problem(
                "analysis_parameter_proposal_invalid",
                str(error),
                "updates",
            )
        output = AnalysisOutput(
            kind="parameter_change_proposal",
            title=selected_id,
            content=proposal,
            metadata={},
        )
        return replace(
            self,
            outputs=(*self.outputs, output),
            parameter_proposals=(*self.parameter_proposals, proposal),
        )

    def candidate_config(
        self,
        selection: CandidateSelection = None,
    ) -> CandidateConfig:
        proposals = _select_candidate_proposals(
            self.parameter_proposals,
            selection=selection,
        )
        return CandidateConfig(
            analysis_title=self.title,
            analysis_key=self.analysis_key,
            parameter_proposals=proposals,
        )

    def save(self) -> SavedAnalysis:
        analysis_key = self.analysis_key
        selected_record_id = f"analysis-{analysis_key}"
        ref = record_content_ref(record_id=selected_record_id, kind="analysis")
        storage = open_run_store(self.run.session.workspace)
        output_artifacts, output_refs = _write_analysis_output_artifacts(
            storage=storage,
            run_id=self.run.id,
            analysis_key=analysis_key,
            step_id=self.step_id,
            analysis_record_id=selected_record_id,
            outputs=self.outputs,
        )
        analysis_record = AnalysisRecord(
            run_id=self.run.id,
            title=self.title,
            key=analysis_key,
            step_id=self.step_id,
            inputs=_analysis_record_inputs(self.inputs),
            outputs=_analysis_record_outputs(
                outputs=self.outputs,
                output_refs=iter(output_refs),
            ),
        )
        write_parameter_change_proposals(
            storage=storage,
            run_id=self.run.id,
            proposals=self.parameter_proposals,
        )
        storage.write_model(self.run.id, ref, analysis_record)
        record = RunRecordEntry(
            id=selected_record_id,
            kind="analysis",
            media_type="application/json",
        )
        write_manifest_records(
            storage=storage,
            manifest=storage.read_manifest(self.run.id),
            records=[record],
        )
        write_manifest_artifacts(
            storage=storage,
            manifest=storage.read_manifest(self.run.id),
            artifacts=output_artifacts,
        )
        return SavedAnalysis(
            record=record,
            analysis_key=analysis_key,
            inputs=self.inputs,
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


def _select_candidate_proposals(
    proposals: Sequence[ParameterChangeProposal],
    *,
    selection: CandidateSelection,
) -> tuple[ParameterChangeProposal, ...]:
    if not proposals:
        _raise_analysis_problem(
            "candidate_config_no_parameter_proposals",
            "candidate config requires at least one parameter proposal",
            "parameter_proposals",
        )
    if selection is None:
        if len(proposals) == 1:
            return (proposals[0],)
        _raise_analysis_problem(
            "candidate_config_selection_required",
            (
                "candidate config selection is required when analysis has multiple "
                "parameter proposals"
            ),
            "selection",
        )
    selected_ids = (selection,) if isinstance(selection, str) else tuple(selection)
    if not selected_ids:
        _raise_analysis_problem(
            "candidate_config_selection_empty",
            "candidate config selection must include at least one parameter proposal",
            "selection",
        )
    by_id = {proposal.id: proposal for proposal in proposals}
    selected: list[ParameterChangeProposal] = []
    seen: set[str] = set()
    for selected_id in selected_ids:
        proposal_id = artifact_slug(selected_id, fallback="analysis")
        if proposal_id in seen:
            _raise_analysis_problem(
                "candidate_config_selection_duplicated",
                f"candidate config selection is duplicated: {proposal_id}",
                "selection",
            )
        try:
            selected.append(by_id[proposal_id])
        except KeyError:
            _raise_analysis_problem(
                "candidate_config_selection_not_found",
                f"candidate config selection was not found: {proposal_id}",
                "selection",
            )
        seen.add(proposal_id)
    return tuple(selected)


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


def _write_analysis_output_artifacts(
    *,
    storage: RunStore,
    run_id: str,
    analysis_key: str,
    step_id: str | None,
    analysis_record_id: str,
    outputs: Sequence[AnalysisOutput],
) -> tuple[
    list[RunArtifactEntry],
    list[str],
]:
    artifact_specs = _analysis_artifact_specs(outputs)
    if not artifact_specs:
        return [], []
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
        metadata.update(
            {
                "artifact_title": spec.title,
            }
        )
        artifact = RunArtifactEntry(
            id=selected_artifact_id,
            kind=spec.kind,
            media_type=media_type,
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
    for prepared in prepared_artifacts:
        _write_analysis_artifact_content(
            storage=storage,
            run_id=run_id,
            ref=artifact_storage_ref(prepared.artifact),
            spec=prepared.spec,
        )
    return (
        [prepared.artifact for prepared in prepared_artifacts],
        [prepared.artifact_id for prepared in prepared_artifacts],
    )


def _analysis_artifact_specs(
    outputs: Sequence[AnalysisOutput],
) -> list[_AnalysisArtifactSpec]:
    specs: list[_AnalysisArtifactSpec] = []
    for output in outputs:
        if output.kind != "artifact":
            continue
        if not isinstance(output.content, _AnalysisArtifactSpec):
            _raise_analysis_problem(
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
    spec: _AnalysisArtifactSpec,
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
    spec: _AnalysisArtifactSpec,
    filename: str,
) -> str:
    if spec.media_type is not None:
        return spec.media_type
    guessed, _encoding = mimetypes.guess_type(filename)
    if guessed is not None:
        return guessed
    return spec.source.default_media_type()


def _write_analysis_artifact_content(
    *,
    storage: RunStore,
    run_id: str,
    ref: str,
    spec: _AnalysisArtifactSpec,
) -> None:
    spec.source.write(storage=storage, run_id=run_id, ref=ref)


def _write_run_bytes(
    storage: RunStore,
    run_id: str,
    ref: str,
    content: bytes,
) -> None:
    path = storage.ref_path(run_id, ref)
    ensure_durable_directory(path.parent)
    path.write_bytes(content)


def _is_artifact_filename(filename: str) -> bool:
    if not filename or "\\" in filename:
        return False
    path = PurePosixPath(filename)
    return path.name == filename and not path.is_absolute() and ".." not in path.parts


def _analysis_key(key: str | None, title: str) -> str:
    selected = key if key is not None else title
    if not selected.strip():
        _raise_analysis_problem(
            "analysis_key_invalid",
            "analysis key must be a non-empty string",
            "key",
        )
    return artifact_slug(selected, fallback="analysis")


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
    "AnalysisContext",
    "AnalysisInput",
    "AnalysisOutput",
    "AnalysisStep",
    "SavedAnalysis",
]

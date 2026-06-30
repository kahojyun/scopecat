"""Analysis facade objects for notebook workflows."""

from __future__ import annotations

import json
import mimetypes
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal, NoReturn, Protocol, cast

from pydantic import BaseModel

from scopecat._manifest_updates import write_manifest_artifacts
from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import Artifact
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.runs.access import RunStore, open_run_store
from scopecat.session_candidate_config import (
    CandidateConfig,
    ParameterGuess,
    analysis_artifact_slug,
)
from scopecat.session_data import Data

if TYPE_CHECKING:
    from scopecat.session_run_handle import RunHandle


AnalysisOutputKind = Literal[
    "note",
    "table",
    "array",
    "figure",
    "guess",
    "external_ref",
    "report",
]


@dataclass(frozen=True)
class AnalysisExternalRef:
    target: str
    target_type: Literal["artifact", "uri"]
    artifact_kind: str | None = None
    path: str | None = None
    media_type: str | None = None


@dataclass(frozen=True)
class AnalysisReportRef:
    target: str
    target_type: Literal["artifact"]
    artifact_kind: str
    path: str
    media_type: str | None = None


@dataclass(frozen=True)
class _AnalysisReportSpec:
    title: str
    source_path: Path | None
    text: str | None
    content: bytes | None
    artifact_id: str | None
    filename: str | None
    media_type: str | None
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class _PreparedAnalysisReport:
    spec: _AnalysisReportSpec
    artifact: Artifact
    ref: AnalysisReportRef


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
    source_artifact_ids: tuple[str, ...] = ()
    report_artifacts: tuple[Artifact, ...] = ()


@dataclass(frozen=True)
class Analysis:
    """In-notebook analysis record for exploratory experiment work."""

    run: RunHandle
    title: str
    outputs: tuple[AnalysisOutput, ...] = ()
    parameter_guesses: tuple[ParameterGuess, ...] = ()

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

    def artifact_ref(
        self,
        selector: str,
        *,
        title: str | None = None,
        expected_kind: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis:
        artifact = self.run.data().artifact(selector, expected_kind=expected_kind)
        external_ref = AnalysisExternalRef(
            target=artifact.id,
            target_type="artifact",
            artifact_kind=artifact.kind,
            path=artifact.path,
            media_type=artifact.media_type,
        )
        return self._with_output(
            "external_ref",
            title or artifact.id,
            external_ref,
            metadata,
        )

    def external_ref(
        self,
        uri: str,
        *,
        title: str = "external ref",
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis:
        if not uri.strip():
            _raise_analysis_diagnostic(
                "analysis_external_ref_invalid",
                "analysis external ref URI must be non-empty",
                "uri",
            )
        return self._with_output(
            "external_ref",
            title,
            AnalysisExternalRef(target=uri, target_type="uri"),
            metadata,
        )

    def report(
        self,
        *,
        title: str,
        path: str | Path | None = None,
        text: str | None = None,
        content: bytes | None = None,
        artifact_id: str | None = None,
        filename: str | None = None,
        media_type: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Analysis:
        if not title.strip():
            _raise_analysis_diagnostic(
                "analysis_report_title_invalid",
                "analysis report title must be a non-empty string",
                "title",
            )
        selected_sources = [value is not None for value in (path, text, content)].count(
            True
        )
        if selected_sources != 1:
            _raise_analysis_diagnostic(
                "analysis_report_source_invalid",
                "analysis report requires exactly one of path, text, or content",
                "report",
            )
        if artifact_id is not None and not artifact_id.strip():
            _raise_analysis_diagnostic(
                "analysis_report_artifact_id_invalid",
                "analysis report artifact id must be a non-empty string",
                "artifact_id",
            )
        if filename is not None and not _is_artifact_filename(filename):
            _raise_analysis_diagnostic(
                "analysis_report_filename_invalid",
                f"analysis report filename must be a basename: {filename}",
                "filename",
            )
        source_path: Path | None = None
        if path is not None:
            source_path = Path(path)
            if not source_path.is_file():
                _raise_analysis_diagnostic(
                    "analysis_report_source_missing",
                    f"analysis report source file is missing: {source_path}",
                    "path",
                )
            selected_filename = filename or source_path.name
            if not _is_artifact_filename(selected_filename):
                _raise_analysis_diagnostic(
                    "analysis_report_filename_invalid",
                    (
                        "analysis report filename must be a basename: "
                        f"{selected_filename}"
                    ),
                    "filename",
                )
        elif filename is None:
            _raise_analysis_diagnostic(
                "analysis_report_filename_missing",
                "analysis report text or bytes content requires filename",
                "filename",
            )
        report_spec = _AnalysisReportSpec(
            title=title,
            source_path=source_path,
            text=text,
            content=content,
            artifact_id=artifact_id,
            filename=filename,
            media_type=media_type,
            metadata=metadata or {},
        )
        return self._with_output("report", title, report_spec, {})

    def guess(
        self,
        parameter_id: str,
        value: object,
        *,
        unit: str | None = None,
        reason: str = "",
        confidence: float | None = None,
    ) -> Analysis:
        if not parameter_id.strip():
            _raise_analysis_diagnostic(
                "analysis_guess_parameter_invalid",
                "analysis guess parameter id must be non-empty",
                "parameter_id",
            )
        if confidence is not None and not 0 <= confidence <= 1:
            _raise_analysis_diagnostic(
                "analysis_guess_confidence_invalid",
                "analysis guess confidence must be between 0 and 1",
                "confidence",
            )
        guess = ParameterGuess(
            parameter_id=parameter_id,
            value=value,
            unit=unit,
            reason=reason,
            confidence=confidence,
        )
        output = AnalysisOutput(
            kind="guess",
            title=parameter_id,
            content=guess,
            metadata={},
        )
        return replace(
            self,
            outputs=(*self.outputs, output),
            parameter_guesses=(*self.parameter_guesses, guess),
        )

    def candidate_config(self, *, reason: str = "") -> CandidateConfig:
        return CandidateConfig(
            source_run_id=self.run.id,
            analysis_title=self.title,
            guesses=self.parameter_guesses,
            reason=reason,
        )

    def promote_step(self, step_id: str) -> PromotedAnalysisStep:
        return PromotedAnalysisStep(id=step_id, source=self)

    def save(self, artifact_id: str | None = None) -> SavedAnalysis:
        selected_artifact_id = (
            artifact_id or f"analysis-{analysis_artifact_slug(self.title)}"
        )
        ref = f"artifacts/{selected_artifact_id}.json"
        source_artifact_ids = _analysis_source_artifact_ids(self.outputs)
        storage = open_run_store(self.run.session.workspace)
        report_artifacts, report_refs = _write_analysis_reports(
            storage=storage,
            run_id=self.run.id,
            analysis_title=self.title,
            analysis_artifact_id=selected_artifact_id,
            outputs=self.outputs,
            source_artifact_ids=source_artifact_ids,
        )
        report_ref_iter = iter(report_refs)
        content = {
            "schema_version": "scopecat.analysis.v1",
            "run_id": self.run.id,
            "title": self.title,
            "source_artifact_ids": list(source_artifact_ids),
            "outputs": [
                {
                    "kind": output.kind,
                    "title": output.title,
                    "content": _json_safe(
                        next(report_ref_iter)
                        if output.kind == "report"
                        else output.content
                    ),
                    "metadata": _json_safe(output.metadata),
                }
                for output in self.outputs
            ],
            "guesses": [_json_safe(guess) for guess in self.parameter_guesses],
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
                "output_kinds": [output.kind for output in self.outputs],
                "guess_count": len(self.parameter_guesses),
                "source_run_id": self.run.id,
                "source_artifact_ids": list(source_artifact_ids),
            },
        )
        write_manifest_artifacts(
            storage=storage,
            manifest=storage.read_manifest(self.run.id),
            artifacts=[artifact, *report_artifacts],
        )
        return SavedAnalysis(
            artifact=artifact,
            path=ref,
            source_artifact_ids=source_artifact_ids,
            report_artifacts=tuple(report_artifacts),
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

    @property
    def config(self) -> ConfigProfileSnapshot:
        return self.run.session.client.run_details(self.run.id).config

    def result(self, title: str = "analysis") -> Analysis:
        return self.run.analysis(title)


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
            title=self.id,
            outputs=self.source.outputs,
            parameter_guesses=self.source.parameter_guesses,
        )


def _analysis_source_artifact_ids(
    outputs: Sequence[AnalysisOutput],
) -> tuple[str, ...]:
    artifact_ids: list[str] = []
    seen: set[str] = set()
    for output in outputs:
        if (
            output.kind != "external_ref"
            or not isinstance(output.content, AnalysisExternalRef)
            or output.content.target_type != "artifact"
        ):
            continue
        artifact_id = output.content.target
        if artifact_id in seen:
            continue
        artifact_ids.append(artifact_id)
        seen.add(artifact_id)
    return tuple(artifact_ids)


def _write_analysis_reports(
    *,
    storage: RunStore,
    run_id: str,
    analysis_title: str,
    analysis_artifact_id: str,
    outputs: Sequence[AnalysisOutput],
    source_artifact_ids: Sequence[str],
) -> tuple[list[Artifact], list[AnalysisReportRef]]:
    specs = _analysis_report_specs(outputs)
    if not specs:
        return [], []
    prepared_reports: list[_PreparedAnalysisReport] = []
    seen_artifact_ids = {analysis_artifact_id}
    seen_filenames = {f"{analysis_artifact_id}.json"}
    default_id_counts: dict[str, int] = {}
    for spec in specs:
        selected_artifact_id = _analysis_report_artifact_id(
            spec,
            analysis_title=analysis_title,
            default_id_counts=default_id_counts,
            seen_artifact_ids=seen_artifact_ids,
        )
        selected_filename = _analysis_report_filename(spec)
        if selected_filename in seen_filenames:
            _raise_analysis_diagnostic(
                "analysis_report_filename_duplicated",
                f"analysis report filename is duplicated: {selected_filename}",
                "filename",
            )
        seen_filenames.add(selected_filename)
        ref = f"artifacts/{selected_filename}"
        media_type = _analysis_report_media_type(spec, selected_filename)
        metadata = _json_mapping(cast("Mapping[object, object]", spec.metadata))
        metadata.update(
            {
                "analysis_title": analysis_title,
                "source_run_id": run_id,
                "source_analysis_artifact_id": analysis_artifact_id,
                "report_title": spec.title,
                "source_artifact_ids": list(source_artifact_ids),
            }
        )
        artifact = Artifact(
            id=selected_artifact_id,
            kind="analysis_report",
            path=ref,
            media_type=media_type,
            metadata=metadata,
        )
        report_ref = AnalysisReportRef(
            target=selected_artifact_id,
            target_type="artifact",
            artifact_kind="analysis_report",
            path=ref,
            media_type=media_type,
        )
        prepared_reports.append(
            _PreparedAnalysisReport(
                spec=spec,
                artifact=artifact,
                ref=report_ref,
            )
        )
    for prepared in prepared_reports:
        _write_analysis_report_content(
            storage=storage,
            run_id=run_id,
            ref=prepared.artifact.path,
            spec=prepared.spec,
        )
    return (
        [prepared.artifact for prepared in prepared_reports],
        [prepared.ref for prepared in prepared_reports],
    )


def _analysis_report_specs(
    outputs: Sequence[AnalysisOutput],
) -> list[_AnalysisReportSpec]:
    specs: list[_AnalysisReportSpec] = []
    for output in outputs:
        if output.kind != "report":
            continue
        if not isinstance(output.content, _AnalysisReportSpec):
            _raise_analysis_diagnostic(
                "analysis_report_output_invalid",
                "analysis report output has invalid content",
                "outputs",
            )
        specs.append(output.content)
    return specs


def _analysis_report_artifact_id(
    spec: _AnalysisReportSpec,
    *,
    analysis_title: str,
    default_id_counts: dict[str, int],
    seen_artifact_ids: set[str],
) -> str:
    if spec.artifact_id is not None:
        if spec.artifact_id in seen_artifact_ids:
            _raise_analysis_diagnostic(
                "analysis_report_artifact_id_duplicated",
                f"analysis report artifact id is duplicated: {spec.artifact_id}",
                "artifact_id",
            )
        seen_artifact_ids.add(spec.artifact_id)
        return spec.artifact_id
    base_id = (
        "analysis-report-"
        f"{analysis_artifact_slug(analysis_title)}-"
        f"{analysis_artifact_slug(spec.title)}"
    )
    count = default_id_counts.get(base_id, 0) + 1
    default_id_counts[base_id] = count
    selected = base_id if count == 1 else f"{base_id}-{count}"
    while selected in seen_artifact_ids:
        count += 1
        default_id_counts[base_id] = count
        selected = f"{base_id}-{count}"
    seen_artifact_ids.add(selected)
    return selected


def _analysis_report_filename(spec: _AnalysisReportSpec) -> str:
    if spec.filename is not None:
        return spec.filename
    if spec.source_path is not None:
        return spec.source_path.name
    _raise_analysis_diagnostic(
        "analysis_report_filename_missing",
        "analysis report text or bytes content requires filename",
        "filename",
    )


def _analysis_report_media_type(
    spec: _AnalysisReportSpec,
    filename: str,
) -> str:
    if spec.media_type is not None:
        return spec.media_type
    guessed, _encoding = mimetypes.guess_type(filename)
    if guessed is not None:
        return guessed
    if spec.text is not None:
        return "text/plain"
    return "application/octet-stream"


def _write_analysis_report_content(
    *,
    storage: RunStore,
    run_id: str,
    ref: str,
    spec: _AnalysisReportSpec,
) -> None:
    if spec.source_path is not None:
        _write_run_bytes(storage, run_id, ref, spec.source_path.read_bytes())
        return
    if spec.text is not None:
        storage.write_text(run_id, ref, spec.text)
        return
    if spec.content is not None:
        _write_run_bytes(storage, run_id, ref, spec.content)
        return
    _raise_analysis_diagnostic(
        "analysis_report_source_invalid",
        "analysis report requires exactly one of path, text, or content",
        "report",
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
    "AnalysisContext",
    "AnalysisExternalRef",
    "AnalysisOutput",
    "AnalysisStep",
    "PromotedAnalysisStep",
    "SavedAnalysis",
]

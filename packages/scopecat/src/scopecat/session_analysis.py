"""Analysis facade objects for notebook workflows."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from typing import TYPE_CHECKING, Literal, Protocol, cast

from pydantic import BaseModel

from scopecat._manifest_updates import write_manifest_artifacts
from scopecat.diagnostics import Diagnostic
from scopecat.errors import ValidationFailed
from scopecat.models.artifact import Artifact
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.runs.access import open_run_store
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
]


@dataclass(frozen=True)
class AnalysisExternalRef:
    target: str
    target_type: Literal["artifact", "uri"]
    artifact_kind: str | None = None
    path: str | None = None
    media_type: str | None = None


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
        content = {
            "schema_version": "scopecat.analysis.v1",
            "run_id": self.run.id,
            "title": self.title,
            "source_artifact_ids": list(source_artifact_ids),
            "outputs": [
                {
                    "kind": output.kind,
                    "title": output.title,
                    "content": _json_safe(output.content),
                    "metadata": _json_safe(output.metadata),
                }
                for output in self.outputs
            ],
            "guesses": [_json_safe(guess) for guess in self.parameter_guesses],
        }
        storage = open_run_store(self.run.session.workspace)
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
            artifacts=[artifact],
        )
        return SavedAnalysis(
            artifact=artifact,
            path=ref,
            source_artifact_ids=source_artifact_ids,
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


def _raise_analysis_diagnostic(code: str, message: str, path: str) -> None:
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

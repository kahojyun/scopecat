"""Candidate configuration facade objects for notebook workflows."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from scopecat._manifest_updates import write_manifest_artifacts
from scopecat.models.artifact import Artifact
from scopecat.models.config import ConfigProfileSnapshot, ConfigProfileSnapshotSource
from scopecat.models.parameter import (
    ParameterChangeSet,
    ParameterPatch,
    Quantity,
)
from scopecat.parameters import apply_parameter_patches, build_parameter_snapshot
from scopecat.runs.access import open_run_store

SAFE_ANALYSIS_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")


@dataclass(frozen=True)
class ParameterGuess:
    parameter_id: str
    value: object
    unit: str | None = None
    reason: str = ""
    confidence: float | None = None


@dataclass(frozen=True)
class CandidateConfig:
    source_run_id: str
    analysis_title: str
    guesses: tuple[ParameterGuess, ...]
    reason: str = ""

    def review(
        self,
        *,
        workspace: str | Path,
        reviewer: str,
        note: str = "",
    ) -> CandidateConfigReview:
        proposal = _candidate_proposal(self)
        proposal_record_ref = f"proposals/{proposal.id}.json"
        candidate_config_record_ref = f"artifacts/{proposal.id}.candidate-config.json"
        storage = open_run_store(workspace)
        source_config = storage.read_config_profile_snapshot(self.source_run_id)
        candidate_config = _candidate_config_snapshot(
            source_config=source_config,
            proposal=proposal,
            proposal_artifact_id=proposal.id,
        )
        reviewed_proposal = proposal.model_copy(update={"state": "approved"})
        storage.write_model(self.source_run_id, proposal_record_ref, reviewed_proposal)
        storage.write_model(
            self.source_run_id,
            candidate_config_record_ref,
            candidate_config,
        )

        proposal_artifact = Artifact(
            id=proposal.id,
            kind="parameter_change_set",
            path=proposal_record_ref,
            media_type="application/json",
            metadata={
                "source": "analysis_candidate_config",
                "analysis_title": self.analysis_title,
                "reviewer": reviewer,
                "note": note,
            },
        )
        candidate_artifact = Artifact(
            id=f"{proposal.id}-candidate-config",
            kind="candidate_config",
            path=candidate_config_record_ref,
            media_type="application/json",
            metadata={
                "source": "analysis_candidate_config",
                "source_proposal_artifact_id": proposal.id,
                "analysis_title": self.analysis_title,
            },
        )
        manifest = storage.read_manifest(self.source_run_id)
        write_manifest_artifacts(
            storage=storage,
            manifest=manifest,
            artifacts=[proposal_artifact, candidate_artifact],
        )
        return CandidateConfigReview(
            candidate=self,
            config=candidate_config,
            proposal_artifact=proposal_artifact,
            candidate_config_artifact=candidate_artifact,
            proposal_artifact_id=proposal_artifact.id,
            candidate_config_artifact_id=candidate_artifact.id,
        )


@dataclass(frozen=True)
class CandidateConfigReview:
    candidate: CandidateConfig
    config: ConfigProfileSnapshot
    proposal_artifact: Artifact
    candidate_config_artifact: Artifact
    proposal_artifact_id: str
    candidate_config_artifact_id: str


def _candidate_proposal(candidate: CandidateConfig) -> ParameterChangeSet:
    patches = [_guess_patch(guess) for guess in candidate.guesses]
    confidence = _candidate_confidence(candidate.guesses)
    return ParameterChangeSet(
        id=f"candidate-{analysis_artifact_slug(candidate.analysis_title)}",
        source_run_id=candidate.source_run_id,
        reason=candidate.reason
        or f"Candidate config from analysis {candidate.analysis_title!r}.",
        patches=patches,
        confidence=confidence,
    )


def _guess_patch(guess: ParameterGuess) -> ParameterPatch:
    if isinstance(guess.value, Quantity):
        value = guess.value
    elif (
        isinstance(guess.value, int | float)
        and not isinstance(guess.value, bool)
        and guess.unit is not None
    ):
        value = Quantity(value=float(guess.value), unit=guess.unit)
    else:
        msg = (
            "candidate config guesses require a Quantity or a numeric value with "
            f"a unit: {guess.parameter_id}"
        )
        raise TypeError(msg)
    return ParameterPatch(
        kind="set_scalar",
        parameter_id=guess.parameter_id,
        value=value,
    )


def _candidate_confidence(guesses: Sequence[ParameterGuess]) -> float | None:
    confidences = [
        guess.confidence for guess in guesses if guess.confidence is not None
    ]
    if not confidences:
        return None
    return min(confidences)


def _candidate_config_snapshot(
    *,
    source_config: ConfigProfileSnapshot,
    proposal: ParameterChangeSet,
    proposal_artifact_id: str,
) -> ConfigProfileSnapshot:
    parameter_state = apply_parameter_patches(
        catalog=source_config.parameter_catalog,
        parameter_state=source_config.parameter_state,
        patches=proposal.patches,
        allow_table_row_changes=True,
    )
    parameter_build = build_parameter_snapshot(
        catalog=source_config.parameter_catalog,
        parameter_state=parameter_state,
    )
    return ConfigProfileSnapshot.model_validate(
        source_config.model_dump(mode="python")
        | {
            "parameter_state": parameter_state,
            "parameter_build": parameter_build,
            "source": ConfigProfileSnapshotSource(
                kind="analysis_candidate_config",
                source_run_id=proposal.source_run_id,
                proposal_id=proposal.id,
                proposal_artifact_id=proposal_artifact_id,
            ),
        }
    )


def analysis_artifact_slug(value: str) -> str:
    slug = SAFE_ANALYSIS_ID_RE.sub("-", value.strip()).strip("-").lower()
    return slug or "analysis"


__all__ = [
    "CandidateConfig",
    "CandidateConfigReview",
    "ParameterGuess",
    "analysis_artifact_slug",
]

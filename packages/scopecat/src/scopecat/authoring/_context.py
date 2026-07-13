"""Config-dependent authoring context used while linking assemblies."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

from scopecat._relations import ParameterRelationData
from scopecat.errors import CheckFailed
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.entity import EntityRef, entity_ref
from scopecat.models.run import RunConfigSource
from scopecat.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)


@dataclass
class ExperimentAuthoringContext:
    config: ConfigProfileSnapshot
    parameters: ParameterRelationData
    workspace: Path
    config_source: RunConfigSource | None = None
    problems: list[Problem] = field(default_factory=list)

    def require_entity(self, entity: EntityRef | str) -> EntityRef:
        selected = entity_ref(entity)
        known = self.config.topology.entity(selected.id)
        if known is None:
            self.raise_problem(
                "unknown_authoring_entity",
                f"experiment authoring references unknown entity {selected.id}",
                root="entity",
                path=(selected.id,),
                category=ProblemCategory.NOT_FOUND,
                details={"entity_id": selected.id},
            )
        if (
            selected.kind is not None
            and known.kind is not None
            and selected.kind != known.kind
        ):
            self.raise_problem(
                "authoring_entity_kind_mismatch",
                f"entity {selected.id} has kind {known.kind}, not {selected.kind}",
                root="entity",
                path=(selected.id,),
                details={
                    "entity_id": selected.id,
                    "actual_kind": known.kind,
                    "requested_kind": selected.kind,
                },
            )
        return EntityRef(
            id=selected.id,
            kind=selected.kind or known.kind,
            metadata={**known.metadata, **selected.metadata},
        )

    def require_entities(
        self,
        entities: Sequence[EntityRef | str],
    ) -> tuple[EntityRef, ...]:
        return tuple(self.require_entity(entity) for entity in entities)

    def problem(
        self,
        code: str,
        message: str,
        root: str,
        *,
        path: Sequence[str | int] = (),
        category: ProblemCategory = ProblemCategory.INVALID_INPUT,
        details: Mapping[str, object] | None = None,
    ) -> Problem:
        return problem(
            code,
            message,
            root=root,
            path=path,
            category=category,
            phase=ProblemPhase.PLANNING,
            details=details,
        )

    def raise_problem(
        self,
        code: str,
        message: str,
        root: str,
        *,
        path: Sequence[str | int] = (),
        category: ProblemCategory = ProblemCategory.INVALID_INPUT,
        details: Mapping[str, object] | None = None,
    ) -> NoReturn:
        raise CheckFailed(
            [
                self.problem(
                    code,
                    message,
                    root=root,
                    path=path,
                    category=category,
                    details=details,
                )
            ]
        )


def problem(
    code: str,
    message: str,
    root: str,
    *,
    path: Sequence[str | int] = (),
    category: ProblemCategory = ProblemCategory.INVALID_INPUT,
    phase: ProblemPhase = ProblemPhase.AUTHORING,
    details: Mapping[str, object] | None = None,
) -> Problem:
    return blocking_problem(
        code=code,
        category=category,
        phase=phase,
        message=message,
        location=model_location(root, *path),
        details=details,
    )


__all__ = [
    "ExperimentAuthoringContext",
    "problem",
]

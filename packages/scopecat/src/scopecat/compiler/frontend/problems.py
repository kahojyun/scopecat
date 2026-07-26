"""Problem construction for config-dependent frontend passes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NoReturn

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.entity_resolution import EntityResolutionError
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    Problem,
    ProblemPhase,
    model_location,
)


def frontend_problem(
    code: str,
    message: str,
    root: str,
    *,
    path: Sequence[str | int] = (),
    phase: ProblemPhase = ProblemPhase.AUTHORING,
    details: Mapping[str, object] | None = None,
) -> Problem:
    """Build one compiler frontend problem without a mutable context object."""

    return compiler_problem(
        code,
        message,
        model_location(root, *path),
        phase=phase,
        details=details,
    )


def raise_frontend_problem(
    code: str,
    message: str,
    root: str,
    *,
    path: Sequence[str | int] = (),
    phase: ProblemPhase = ProblemPhase.PLANNING,
    details: Mapping[str, object] | None = None,
) -> NoReturn:
    raise CheckFailed(
        (
            frontend_problem(
                code,
                message,
                root,
                path=path,
                phase=phase,
                details=details,
            ),
        )
    )


def raise_entity_resolution_problem(error: EntityResolutionError) -> NoReturn:
    """Translate shared entity-resolution failures at the frontend boundary."""

    issue = error.issue
    if issue.code == "unknown_entity":
        raise_frontend_problem(
            "unknown_authoring_entity",
            f"experiment authoring references unknown entity {issue.entity_id}",
            "entity",
            path=(issue.entity_id,),
            details={"entity_id": issue.entity_id},
        )
    raise_frontend_problem(
        "authoring_entity_kind_mismatch",
        f"entity {issue.entity_id} has kind {issue.actual_kind}, "
        f"not {issue.requested_kind}",
        "entity",
        path=(issue.entity_id,),
        details={
            "entity_id": issue.entity_id,
            "actual_kind": issue.actual_kind,
            "requested_kind": issue.requested_kind,
        },
    )

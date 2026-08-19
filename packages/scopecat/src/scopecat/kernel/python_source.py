"""Deterministic lexical identities for project-owned Python definitions."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from textwrap import dedent
from typing import TypedDict


class PythonSourceIdentity(TypedDict):
    """Import location and normalized lexical source for one definition."""

    module: str
    qualname: str
    source: str


type PythonSourceDefinition = Callable[..., object] | type[object]


def require_no_python_nonlocals(
    definition: Callable[..., object],
    *,
    label: str,
) -> None:
    """Reject hidden callback state that is not represented by durable inputs."""

    captures = tuple(sorted(inspect.getclosurevars(definition).nonlocals))
    if captures:
        raise TypeError(
            f"{label} must not capture nonlocal values: {', '.join(captures)}"
        )


def python_source_identity(
    definition: PythonSourceDefinition,
    *,
    label: str,
) -> PythonSourceIdentity:
    """Return source identity without claiming to cover transitive dependencies."""

    try:
        source = dedent(inspect.getsource(definition)).strip()
    except (OSError, TypeError) as error:
        raise TypeError(f"{label} source must be available to fingerprint") from error
    if not source:
        raise TypeError(f"{label} source must be non-empty")
    return {
        "module": definition.__module__,
        "qualname": definition.__qualname__,
        "source": source,
    }


__all__ = [
    "PythonSourceIdentity",
    "python_source_identity",
    "require_no_python_nonlocals",
]

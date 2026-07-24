"""Discovery and validation for a user-owned Scopecat lab project."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

_MANIFEST_NAME = "scopecat.toml"
_LAB_KEYS = frozenset({"application", "bootstrap-config"})


class ProjectManifestError(ValueError):
    """A discovered project manifest cannot define a lab application."""


@dataclass(frozen=True, slots=True)
class LabProject:
    """One code project paired with its default daemon-owned instance."""

    root: Path
    manifest: Path
    application: str | None
    bootstrap_config: Path | None


def discover_lab_project(start: str | Path = ".") -> LabProject:
    """Find ``scopecat.toml`` at or above ``start`` and load its lab settings."""

    selected = Path(start).resolve()
    if selected.is_file():
        if selected.name != _MANIFEST_NAME:
            raise ProjectManifestError(
                f"project manifest must be named {_MANIFEST_NAME}"
            )
        return load_lab_project(selected)

    for root in (selected, *selected.parents):
        manifest = root / _MANIFEST_NAME
        if manifest.is_file():
            return load_lab_project(manifest)
    raise ProjectManifestError(f"no {_MANIFEST_NAME} found at or above {selected}")


def load_lab_project(manifest: str | Path) -> LabProject:
    """Load the small project contract used by daemon and notebook tooling."""

    selected = Path(manifest).resolve()
    try:
        document = cast(
            "dict[str, object]",
            tomllib.loads(selected.read_text(encoding="utf-8")),
        )
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ProjectManifestError(
            f"cannot read project manifest {selected}: {error}"
        ) from error

    lab_value = document.get("lab")
    if not isinstance(lab_value, dict):
        raise ProjectManifestError("scopecat.toml requires a [lab] table")
    lab = cast("dict[str, object]", lab_value)
    unknown = set(lab) - _LAB_KEYS
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise ProjectManifestError(f"unknown [lab] field(s): {fields}")

    application = _optional_text(lab, "application")
    bootstrap_value = _optional_text(lab, "bootstrap-config")
    bootstrap_config = (
        None
        if bootstrap_value is None
        else (selected.parent / bootstrap_value).resolve()
    )
    if bootstrap_config is not None and not bootstrap_config.is_file():
        raise ProjectManifestError(
            f"bootstrap config does not exist: {bootstrap_config}"
        )
    if application is None and bootstrap_config is None:
        raise ProjectManifestError("[lab] requires application or bootstrap-config")
    return LabProject(
        root=selected.parent,
        manifest=selected,
        application=application,
        bootstrap_config=bootstrap_config,
    )


def _optional_text(table: dict[str, object], field: str) -> str | None:
    value = table.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ProjectManifestError(f"[lab].{field} must be a non-empty string")
    return value


__all__ = [
    "LabProject",
    "ProjectManifestError",
    "discover_lab_project",
    "load_lab_project",
]

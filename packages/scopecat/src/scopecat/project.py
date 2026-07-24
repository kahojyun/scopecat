"""Discovery and application loading for a user-owned Scopecat lab project."""

from __future__ import annotations

import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, replace
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, cast

from scopecat.application.lab import LabApplication
from scopecat.daemon.endpoint import resolve_daemon_endpoint
from scopecat.planning.system import ExperimentSystemBuilder

if TYPE_CHECKING:
    from scopecat.api.lab import LabClient

type LabApplicationFactory = Callable[[Path], LabApplication]

_MANIFEST_NAME = "scopecat.toml"
_LAB_KEYS = frozenset({"application"})


class ProjectManifestError(ValueError):
    """A discovered project manifest cannot define a lab application."""


@dataclass(frozen=True, slots=True)
class Project:
    """One code project paired with its default daemon-owned instance."""

    root: Path
    manifest: Path
    application_spec: str | None

    def load_application(self) -> LabApplication:
        """Load the version-controlled composition declared by this project."""

        if self.application_spec is None:
            return LabApplication()
        return load_application_factory(self.application_spec, self.root)(self.root)

    def connect(
        self,
        daemon: str | None = None,
        *,
        build_system: ExperimentSystemBuilder | None = None,
    ) -> LabClient:
        """Open the project's high-level notebook client."""

        endpoint = resolve_daemon_endpoint(self.root, explicit=daemon)
        application = self.load_application()
        if build_system is not None:
            application = replace(application, build_system=build_system)
        return application.connect(endpoint)


def open_project(start: str | Path = ".") -> Project:
    """Find ``scopecat.toml`` at or above ``start`` and load its lab settings."""

    selected = Path(start).resolve()
    if selected.is_file():
        if selected.name != _MANIFEST_NAME:
            raise ProjectManifestError(
                f"project manifest must be named {_MANIFEST_NAME}"
            )
        return load_project(selected)

    for root in (selected, *selected.parents):
        manifest = root / _MANIFEST_NAME
        if manifest.is_file():
            return load_project(manifest)
    raise ProjectManifestError(f"no {_MANIFEST_NAME} found at or above {selected}")


def load_project(manifest: str | Path) -> Project:
    """Load the project contract shared by daemon and notebook tooling."""

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
    return Project(
        root=selected.parent,
        manifest=selected,
        application_spec=application,
    )


def load_application_factory(
    spec: str,
    project_root: str | Path,
) -> LabApplicationFactory:
    """Load the application factory named by ``MODULE:CALLABLE``."""

    module_name, separator, attribute_name = spec.partition(":")
    if not separator or not module_name or not attribute_name:
        raise ValueError("lab application must use MODULE:CALLABLE")

    root = Path(project_root).resolve()
    # Project imports may continue lazily after startup, so both source roots
    # remain available for the process lifetime.
    for path in (root, root / "src"):
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))
    return cast(
        "LabApplicationFactory",
        getattr(import_module(module_name), attribute_name),
    )


def _optional_text(table: dict[str, object], field: str) -> str | None:
    value = table.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ProjectManifestError(f"[lab].{field} must be a non-empty string")
    return value


__all__ = [
    "LabApplicationFactory",
    "Project",
    "ProjectManifestError",
    "load_application_factory",
    "load_project",
    "open_project",
]

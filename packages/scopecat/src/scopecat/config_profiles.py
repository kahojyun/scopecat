"""File-backed config profile loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from scopecat.models.config import (
    ConfigProfileSnapshot,
    EnvironmentSpec,
    SystemSpec,
    snapshot_config_profile,
)
from scopecat.models.parameter import ParameterState


class ConfigProfileFile(BaseModel):
    """User-authored file that references split config inputs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.config_profile.v0"] = "scopecat.config_profile.v0"
    id: str
    system_ref: str
    environment_ref: str
    parameter_state_ref: str
    metadata: dict[str, Any] = Field(default_factory=dict)


def load_config_profile(path: str | Path) -> ConfigProfileSnapshot:
    """Load a file-backed config profile and freeze referenced config inputs."""

    profile_path = Path(path)
    profile = ConfigProfileFile.model_validate_json(profile_path.read_text())
    base_dir = profile_path.parent
    system_path = _resolve_profile_ref(base_dir, profile.system_ref)
    environment_path = _resolve_profile_ref(base_dir, profile.environment_ref)
    parameter_state_path = _resolve_profile_ref(base_dir, profile.parameter_state_ref)
    system = SystemSpec.model_validate_json(system_path.read_text())
    environment = EnvironmentSpec.model_validate_json(environment_path.read_text())
    parameter_state = ParameterState.model_validate_json(
        parameter_state_path.read_text()
    )
    return snapshot_config_profile(
        profile_id=profile.id,
        system=system,
        environment=environment,
        parameter_state=parameter_state,
        metadata=profile.metadata,
    )


def _resolve_profile_ref(base_dir: Path, ref: str) -> Path:
    path = Path(ref)
    if path.is_absolute():
        return path
    return base_dir / path


__all__ = ["ConfigProfileFile", "load_config_profile"]

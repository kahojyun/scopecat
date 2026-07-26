"""File-backed config profile loading."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from scopecat.kernel.errors import DataIntegrityError, NotFound, StorageError
from scopecat.kernel.problems import (
    ExternalLocation,
    Problem,
    ProblemPhase,
)
from scopecat.records.config import (
    ConfigProfileSnapshot,
    SystemSpec,
    snapshot_config_profile,
)
from scopecat.records.parameter import ParameterSnapshot


class ConfigProfileManifest(BaseModel):
    """User-authored file that references split config inputs."""

    model_config = ConfigDict(extra="forbid")

    format_version: Literal["scopecat.config_profile_manifest.v1"] = (
        "scopecat.config_profile_manifest.v1"
    )
    id: str
    system_ref: str
    parameter_snapshot_ref: str


def load_config_profile(path: str | Path) -> ConfigProfileSnapshot:
    """Load a file-backed config profile and freeze referenced config inputs."""

    profile_path = Path(path)
    profile = _load_config_input(
        profile_path,
        ConfigProfileManifest,
        code_prefix="config.profile",
        label="config profile",
    )
    base_dir = profile_path.parent
    system_path = _resolve_profile_ref(base_dir, profile.system_ref)
    parameter_snapshot_path = _resolve_profile_ref(
        base_dir, profile.parameter_snapshot_ref
    )
    system = _load_config_input(
        system_path,
        SystemSpec,
        code_prefix="config.system",
        label="system specification",
    )
    parameter_snapshot = _load_config_input(
        parameter_snapshot_path,
        ParameterSnapshot,
        code_prefix="config.parameter_snapshot",
        label="parameter snapshot",
    )
    try:
        return snapshot_config_profile(
            profile_id=profile.id,
            system=system,
            parameter_snapshot=parameter_snapshot,
        )
    except ValidationError as error:
        raise DataIntegrityError(
            [
                _config_problem(
                    code="config.snapshot.invalid",
                    message="config profile inputs do not form a valid snapshot",
                    path=profile_path,
                )
            ]
        ) from error


def _resolve_profile_ref(base_dir: Path, ref: str) -> Path:
    path = Path(ref)
    if path.is_absolute():
        return path
    return base_dir / path


def _load_config_input[TModel: BaseModel](
    path: Path,
    model_type: type[TModel],
    *,
    code_prefix: str,
    label: str,
) -> TModel:
    try:
        content = path.read_text()
    except FileNotFoundError as error:
        raise NotFound(
            [
                _config_problem(
                    code=f"{code_prefix}.not_found",
                    message=f"{label} was not found",
                    path=path,
                )
            ]
        ) from error
    except IsADirectoryError as error:
        raise DataIntegrityError(
            [
                _config_problem(
                    code=f"{code_prefix}.not_file",
                    message=f"{label} is not a readable file",
                    path=path,
                )
            ]
        ) from error
    except OSError as error:
        raise StorageError(
            [
                _config_problem(
                    code="config.read_failed",
                    message="config input could not be read",
                    path=path,
                )
            ]
        ) from error
    except UnicodeError as error:
        raise DataIntegrityError(
            [
                _config_problem(
                    code=f"{code_prefix}.invalid_encoding",
                    message=f"{label} is not valid text",
                    path=path,
                )
            ]
        ) from error

    try:
        return model_type.model_validate_json(content)
    except ValidationError as error:
        raise DataIntegrityError(
            [
                _config_problem(
                    code=f"{code_prefix}.invalid",
                    message=f"{label} does not match its schema",
                    path=path,
                )
            ]
        ) from error


def _config_problem(
    *,
    code: str,
    message: str,
    path: Path,
) -> Problem:
    return Problem(
        code=code,
        phase=ProblemPhase.CONFIGURATION,
        message=message,
        location=ExternalLocation(uri=str(path)),
    )

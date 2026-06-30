"""Notebook-style example: open the demo lab workspace."""

# ruff: noqa: E402

from __future__ import annotations

# %%
import sys
from dataclasses import dataclass
from pathlib import Path

EXAMPLE_ROOT = Path(__file__).resolve().parents[1]
if str(EXAMPLE_ROOT) not in sys.path:
    sys.path.insert(0, str(EXAMPLE_ROOT))

# %%
import scopecat as sc
from quantum_lab_demo import (
    DEFAULT_WORKSPACE_ROOT,
    READOUT_FREQUENCY_FIXTURE_DIR,
    READOUT_FREQUENCY_VIRTUAL_LAB_PROFILE,
    readout_frequency_lab,
)

DEFAULT_WORKSPACE = DEFAULT_WORKSPACE_ROOT / "notebooks" / "01-open-workspace"


@dataclass(frozen=True)
class OpenWorkspaceResult:
    workspace: sc.Workspace
    workspace_path: Path
    config_profile: Path
    virtual_lab_profile: Path


# %%
def open_lab(workspace: str | Path = DEFAULT_WORKSPACE) -> sc.Workspace:
    return readout_frequency_lab(workspace=workspace)


# %%
def run(workspace: str | Path = DEFAULT_WORKSPACE) -> OpenWorkspaceResult:
    lab = open_lab(workspace)
    return OpenWorkspaceResult(
        workspace=lab,
        workspace_path=Path(workspace),
        config_profile=READOUT_FREQUENCY_FIXTURE_DIR / "config-profile.json",
        virtual_lab_profile=READOUT_FREQUENCY_VIRTUAL_LAB_PROFILE,
    )


# %%
def format_summary(result: OpenWorkspaceResult) -> str:
    return "\n".join(
        [
            f"Workspace: {result.workspace_path}",
            f"Config: {result.config_profile.name}",
            f"Virtual lab: {result.virtual_lab_profile.name}",
        ]
    )


if __name__ == "__main__":
    print(format_summary(run()))

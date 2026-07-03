"""Preview planning workflow for the quantum examples."""

from __future__ import annotations

from pathlib import Path

import scopecat as sc
import scopecat.experiments as experiments
import scopecat.relations as relations
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile

from quantum_lab_demo.fixtures import DEFAULT_WORKSPACE_ROOT, REPO_ROOT

DEFAULT_PREVIEW_WORKSPACE = DEFAULT_WORKSPACE_ROOT / "preview"
CORE_FIXTURE_DIR = REPO_ROOT / "fixtures" / "core" / "simple_scan"


def drive_scan() -> experiments.ExperimentSpec:
    return experiments.experiment(
        id="drive-scan",
        kind="drive.frequency_scan",
        points=relations.grid(frequency=relations.linspace(4.9, 5.1, 3, unit="GHz")),
        params=[
            experiments.set_param(
                "drive_frequency",
                relations.col("frequency"),
            )
        ],
        state=[
            experiments.set_state(
                "source-0",
                "frequency",
                relations.param("drive_frequency"),
            )
        ],
        acquire=experiments.acquire(
            "iq",
            shots=4,
            record="shot",
            observations=[experiments.point("signal", unit="ratio")],
        ),
    )


def load_preview_config() -> ConfigProfileSnapshot:
    return load_config_profile(CORE_FIXTURE_DIR / "config-profile.json")


def preview_drive_scan(
    *,
    workspace: str | Path = DEFAULT_PREVIEW_WORKSPACE,
) -> sc.PreviewExperimentResult:
    lab = sc.open(
        workspace=workspace,
        config_profile=load_preview_config(),
    )
    experiment = lab.experiment("drive scan", source=drive_scan())
    return lab.preview(experiment)


def format_preview_summary(preview: sc.PreviewExperimentResult) -> str:
    plan = preview.plan
    return "\n".join(
        [
            f"Experiment: {preview.experiment.id}",
            f"Points: {len(plan.points)}",
            f"Result intents: {', '.join(intent.id for intent in plan.result_intents)}",
            f"Plan hash: {plan.content_hash}",
        ]
    )


__all__ = [
    "DEFAULT_PREVIEW_WORKSPACE",
    "drive_scan",
    "format_preview_summary",
    "load_preview_config",
    "preview_drive_scan",
]

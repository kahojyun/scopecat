"""Dry-run planning workflow for the quantum examples."""

from __future__ import annotations

from pathlib import Path

import scopecat as sc
import scopecat.experiments as experiments
import scopecat.relations as relations
from scopecat.experiments import DryRunSnapshot
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile

from quantum_lab_demo.fixtures import DEFAULT_WORKSPACE_ROOT, REPO_ROOT

DEFAULT_DRY_RUN_WORKSPACE = DEFAULT_WORKSPACE_ROOT / "dry-run"
CORE_FIXTURE_DIR = REPO_ROOT / "fixtures" / "core" / "simulated_scan"


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


def load_dry_run_config() -> ConfigProfileSnapshot:
    return load_config_profile(CORE_FIXTURE_DIR / "config-profile.json")


def run_dry_run_plan(
    *,
    workspace: str | Path = DEFAULT_DRY_RUN_WORKSPACE,
) -> sc.Run:
    lab = sc.open(
        workspace=workspace,
        config_profile=load_dry_run_config(),
        mode="dry",
    )
    experiment = lab.experiment("drive scan", source=drive_scan())
    return lab.run(experiment)


def format_dry_run_summary(run: sc.Run) -> str:
    snapshot = run.result.snapshot
    if not isinstance(snapshot, DryRunSnapshot):
        msg = "dry-run example expected a dry-run snapshot"
        raise TypeError(msg)
    plan = snapshot.plan
    return "\n".join(
        [
            f"Run: {run.manifest.run_id}",
            f"Experiment: {snapshot.experiment_id}",
            f"Runner: {run.manifest.runner_id}",
            f"Points: {snapshot.point_count}",
            f"Result intents: {', '.join(intent.id for intent in plan.result_intents)}",
            f"Plan hash: {plan.content_hash}",
        ]
    )


__all__ = [
    "DEFAULT_DRY_RUN_WORKSPACE",
    "drive_scan",
    "format_dry_run_summary",
    "load_dry_run_config",
    "run_dry_run_plan",
]

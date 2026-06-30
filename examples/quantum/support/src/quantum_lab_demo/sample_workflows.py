"""Reusable sample-backed native experiment workflows."""

from __future__ import annotations

from dataclasses import dataclass

import scopecat as sc

from quantum_lab_demo.fixtures import (
    DEFAULT_SAMPLE_TEMPLATES_WORKSPACE,
    SAMPLE_TEMPLATES_FIXTURE_DIR,
)
from quantum_lab_demo.lab import PathInput, sample_native_lab
from quantum_lab_demo.sample import (
    cz_rb,
    rabi,
    readout_frequency,
    sqg_rb,
)


@dataclass(frozen=True)
class SampleNativeExperimentsResult:
    rabi: sc.RunHandle
    readout: sc.RunHandle
    sqg_rb: sc.RunHandle
    cz_rb: sc.RunHandle

    @property
    def runs(self) -> tuple[sc.RunHandle, ...]:
        return (
            self.rabi,
            self.readout,
            self.sqg_rb,
            self.cz_rb,
        )

    @property
    def template_ids(self) -> tuple[str, ...]:
        return tuple(
            run.resolved_experiment.template_id
            for run in self.runs
            if run.resolved_experiment is not None
            and run.resolved_experiment.template_id is not None
        )


def run_sample_native_experiments(
    *,
    qubit: str = "q0",
    coupled_qubit: str = "q1",
    lab: sc.Workspace | None = None,
    workspace: PathInput = DEFAULT_SAMPLE_TEMPLATES_WORKSPACE,
    config_profile: PathInput = SAMPLE_TEMPLATES_FIXTURE_DIR / "config-profile.json",
) -> SampleNativeExperimentsResult:
    active_lab = lab or sample_native_lab(
        workspace=workspace,
        config_profile=config_profile,
    )

    return SampleNativeExperimentsResult(
        rabi=run_rabi_experiment(qubit=qubit, lab=active_lab),
        readout=run_sample_readout_frequency(qubit=qubit, lab=active_lab),
        sqg_rb=run_sqg_rb_experiment(
            qubit=qubit,
            lengths=[4, 8, 16],
            seed=11,
            lab=active_lab,
        ),
        cz_rb=run_cz_rb_experiment(
            control_qubit=qubit,
            partner_qubit=coupled_qubit,
            lengths=[2, 4, 8],
            seed=17,
            lab=active_lab,
        ),
    )


def run_rabi_experiment(
    *,
    qubit: str,
    lab: sc.Workspace,
) -> sc.RunHandle:
    return lab.run(rabi(qubit=qubit))


def run_sample_readout_frequency(
    *,
    qubit: str,
    lab: sc.Workspace,
) -> sc.RunHandle:
    return lab.run(readout_frequency(qubit=qubit))


def run_sqg_rb_experiment(
    *,
    qubit: str,
    lengths: list[int],
    seed: int,
    lab: sc.Workspace,
) -> sc.RunHandle:
    return lab.run(sqg_rb(qubit=qubit, lengths=lengths, seed=seed))


def run_cz_rb_experiment(
    *,
    control_qubit: str,
    partner_qubit: str,
    lengths: list[int],
    seed: int,
    lab: sc.Workspace,
) -> sc.RunHandle:
    return lab.run(
        cz_rb(
            control_qubit=control_qubit,
            partner_qubit=partner_qubit,
            lengths=lengths,
            seed=seed,
        )
    )


def format_sample_native_experiments_summary(
    result: SampleNativeExperimentsResult,
) -> str:
    lines = []
    for run in result.runs:
        template_id = (
            run.resolved_experiment.template_id
            if run.resolved_experiment is not None
            else "unknown"
        )
        lines.append(f"{template_id}: {run.id}")
    return "\n".join(lines)


__all__ = [
    "SampleNativeExperimentsResult",
    "format_sample_native_experiments_summary",
    "run_cz_rb_experiment",
    "run_rabi_experiment",
    "run_sample_native_experiments",
    "run_sample_readout_frequency",
    "run_sqg_rb_experiment",
]

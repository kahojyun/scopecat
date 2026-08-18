from __future__ import annotations

from pathlib import Path

from scopecat.analysis.service import AnalysisParameterProposalOutput, save_analysis
from scopecat.config.changes import (
    parameter_change_proposal_from_updates,
)
from scopecat.config.parameters import replace_scalar_parameter
from scopecat.kernel.quantity import Quantity

from scopecat_testkit.config_registry import load_config
from scopecat_testkit.server.runtime import sqlite_project_services
from scopecat_testkit.server.signal_testkit import execute_signal_run
from scopecat_testkit.workflow_fixtures import load_invocation


def signal_run_with_parameter_change(tmp_path: Path) -> str:
    manifest = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        project_root=tmp_path,
    )
    seed_best_signal_parameter_change(tmp_path=tmp_path, run_id=manifest.run_id)
    return manifest.run_id


def seed_best_signal_parameter_change(*, tmp_path: Path, run_id: str) -> None:
    storage = sqlite_project_services(tmp_path).runs
    config = storage.read_config_profile_snapshot(run_id)
    proposal = parameter_change_proposal_from_updates(
        source_run_id=run_id,
        source_config=config,
        analysis_title="best signal fixture",
        analysis_record_id="analysis-best-signal-fixture-r1",
        proposal_id="best-signal",
        updates=(
            replace_scalar_parameter(
                "drive_frequency",
                Quantity(value=5.1, unit="GHz"),
            ),
        ),
        reason="Best signal fixture parameter change.",
        confidence=1.0,
    )
    save_analysis(
        services=sqlite_project_services(tmp_path),
        run_id=run_id,
        title="best signal fixture",
        analysis_key="best-signal-fixture",
        step_id=None,
        inputs=(),
        executions=(),
        outputs=(
            AnalysisParameterProposalOutput(
                kind="parameter_change_proposal",
                id=proposal.id,
                title=proposal.id,
                content=proposal,
                metadata={},
            ),
        ),
        parameter_proposals=(proposal,),
    )

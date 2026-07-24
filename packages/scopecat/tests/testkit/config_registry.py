from __future__ import annotations

from pathlib import Path

from scopecat.analysis.service import AnalysisOutput, save_analysis
from scopecat.composition.embedded import embedded_workspace_services
from scopecat.config.candidates import CandidateConfig
from scopecat.config.changes import (
    load_parameter_change_proposal,
    parameter_change_proposal_from_updates,
    review_parameter_change_proposal,
)
from scopecat.config.parameters import replace_scalar_parameter
from scopecat.config.profiles import load_config_profile
from scopecat.config.resolution import register_and_activate_candidate_config
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter import Quantity
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR
from tests.testkit.signal_testkit import execute_signal_run
from tests.testkit.workflow_fixtures import load_invocation


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def signal_run_with_parameter_change(tmp_path: Path) -> str:
    manifest = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        workspace=tmp_path,
    )
    seed_best_signal_parameter_change(tmp_path=tmp_path, run_id=manifest.run_id)
    return manifest.run_id


def seed_best_signal_parameter_change(*, tmp_path: Path, run_id: str) -> None:
    storage = embedded_workspace_services(tmp_path).runs
    config = storage.read_config_profile_snapshot(run_id)
    proposal = parameter_change_proposal_from_updates(
        source_run_id=run_id,
        source_config=config,
        analysis_title="best signal fixture",
        analysis_record_id="analysis-best-signal-fixture",
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
        services=embedded_workspace_services(tmp_path),
        run_id=run_id,
        title="best signal fixture",
        analysis_key="best-signal-fixture",
        step_id=None,
        inputs=(),
        outputs=(
            AnalysisOutput(
                kind="parameter_change_proposal",
                title=proposal.id,
                content=proposal,
                metadata={},
            ),
        ),
        parameter_proposals=(proposal,),
    )


def activate_best_signal(
    tmp_path: Path,
    run_id: str,
    *,
    entry_id: str = "best-signal-entry",
) -> str:
    services = embedded_workspace_services(tmp_path)
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        services=services,
    )
    candidate = CandidateConfig(
        parameter_proposals=(proposal,),
    )
    review_parameter_change_proposal(
        run_id=run_id,
        selector=proposal.id,
        services=services,
        state="approved",
        reviewer="operator",
    )
    activation = register_and_activate_candidate_config(
        candidate=candidate,
        services=services,
        entry_id=entry_id,
        registered_by="operator",
        operator="operator",
        note="activate best signal",
    )
    return activation.entry.id

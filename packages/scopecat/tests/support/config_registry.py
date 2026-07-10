from __future__ import annotations

from pathlib import Path

from scopecat._workflows.config import register_and_activate_candidate_config
from scopecat.candidate_configs import CandidateConfig
from scopecat.config_profiles import load_config_profile
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import Quantity
from scopecat.parameter_changes import (
    load_parameter_change_proposal,
    parameter_change_proposal_from_updates,
    review_parameter_change_proposal,
    write_parameter_change_proposals,
)
from scopecat.parameters import replace_scalar_parameter
from scopecat.runs import open_run_store
from tests.support.signal_testkit import execute_signal_run
from tests.support.workflow_fixtures import load_invocation

EXAMPLE_DIR = Path(__file__).parents[4] / "fixtures" / "core" / "simple_scan"


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def signal_run_with_parameter_change(tmp_path: Path) -> str:
    manifest, _snapshot = execute_signal_run(
        config=load_config(),
        experiment=load_invocation(),
        workspace=tmp_path,
    )
    seed_best_signal_parameter_change(tmp_path=tmp_path, run_id=manifest.run_id)
    return manifest.run_id


def seed_best_signal_parameter_change(*, tmp_path: Path, run_id: str) -> None:
    storage = open_run_store(tmp_path)
    config = storage.read_config_profile_snapshot(run_id)
    proposal = parameter_change_proposal_from_updates(
        source_run_id=run_id,
        source_config=config,
        analysis_title="best signal fixture",
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
    write_parameter_change_proposals(
        storage=storage,
        run_id=run_id,
        proposals=(proposal,),
    )


def activate_best_signal(
    tmp_path: Path,
    run_id: str,
    *,
    entry_id: str = "best-signal-entry",
) -> str:
    proposal = load_parameter_change_proposal(
        run_id=run_id,
        selector="best-signal",
        workspace=tmp_path,
    )
    candidate = CandidateConfig(
        analysis_title="best signal fixture",
        analysis_key="best-signal",
        parameter_proposals=(proposal,),
    )
    review_parameter_change_proposal(
        run_id=run_id,
        selector=proposal.id,
        workspace=tmp_path,
        state="approved",
        reviewer="operator",
    )
    activation = register_and_activate_candidate_config(
        candidate=candidate,
        workspace=tmp_path,
        entry_id=entry_id,
        registered_by="operator",
        operator="operator",
        note="activate best signal",
    )
    return activation.entry.id

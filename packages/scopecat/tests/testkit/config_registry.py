from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from scopecat.analysis.service import AnalysisOutput, save_analysis
from scopecat.application.services import ProjectStateServices
from scopecat.config.changes import (
    _prepare_parameter_change_decision,
    parameter_change_proposal_from_updates,
    prepare_parameter_change_decision,
    prepare_parameter_change_review,
)
from scopecat.config.parameters import replace_scalar_parameter
from scopecat.config.profiles import load_config_profile
from scopecat.config.registry.ports import ConfigRegistryUnitOfWorkFactory
from scopecat.config.registry.records import ConfigRegistryEntry
from scopecat.config.registry.service import (
    _register_candidate_config_locked,
    _validate_entry_id,
    _validate_required_text,
    load_config_registry_entry_snapshot,
)
from scopecat.records.config import ConfigContentHash, ConfigProfileSnapshot
from scopecat.records.parameter import Quantity
from scopecat.records.parameter_change import (
    HumanDecisionAuthority,
    ParameterChangeDecisionAuthority,
    ParameterChangeDecisionRecord,
    ParameterChangeReviewState,
)
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR
from tests.testkit.runtime import sqlite_project_services
from tests.testkit.signal_testkit import execute_signal_run
from tests.testkit.workflow_fixtures import load_invocation


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def load_config_registry_entry(
    *,
    entry_id: str,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
) -> ConfigRegistryEntry:
    return load_config_registry_entry_snapshot(
        entry_id=entry_id,
        unit_of_work=unit_of_work,
    ).entry


def load_config_registry_config(
    *,
    entry_id: str,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
) -> ConfigProfileSnapshot:
    return load_config_registry_entry_snapshot(
        entry_id=entry_id,
        unit_of_work=unit_of_work,
    ).config


def register_candidate_config(
    *,
    config: ConfigProfileSnapshot,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
    entry_id: str,
    registered_by: str,
    run_id: str,
    proposal_ids: Sequence[str],
    base_config_content_hash: ConfigContentHash,
    note: str = "",
) -> ConfigRegistryEntry:
    """Register without activation for persistence tests."""

    _validate_entry_id(entry_id)
    _validate_required_text(registered_by, field="registered_by")
    _validate_required_text(run_id, field="run_id")
    for proposal_id in proposal_ids:
        _validate_required_text(proposal_id, field="proposal_ids")
    with unit_of_work() as work:
        return _register_candidate_config_locked(
            config=config,
            work=work,
            entry_id=entry_id,
            registered_by=registered_by,
            run_id=run_id,
            proposal_ids=proposal_ids,
            base_config_content_hash=base_config_content_hash,
            note=note,
        )


def review_parameter_change_proposal(
    *,
    run_id: str,
    selector: str,
    services: ProjectStateServices,
    state: ParameterChangeReviewState,
    reviewer: str,
    note: str = "",
) -> ParameterChangeDecisionRecord:
    prepared = prepare_parameter_change_review(
        run_id=run_id,
        selector=selector,
        services=services,
        state=state,
        reviewer=reviewer,
        note=note,
    )
    services.runs.publish_content(prepared.publication)
    return prepared.decision


def decide_parameter_change_proposal(
    *,
    run_id: str,
    selector: str,
    services: ProjectStateServices,
    decision: ParameterChangeReviewState,
    authority: ParameterChangeDecisionAuthority,
    note: str = "",
) -> ParameterChangeDecisionRecord:
    prepared = prepare_parameter_change_decision(
        run_id=run_id,
        selector=selector,
        services=services,
        decision=decision,
        authority=authority,
        note=note,
    )
    services.runs.publish_content(prepared.publication)
    return prepared.decision


def invalidate_parameter_change_proposal(
    *,
    run_id: str,
    selector: str,
    services: ProjectStateServices,
    reason: str,
    invalidated_by: str,
    invalidated_by_refs: list[str] | None = None,
) -> ParameterChangeDecisionRecord:
    prepared = _prepare_parameter_change_decision(
        run_id=run_id,
        selector=selector,
        services=services,
        decision="invalidated",
        authority=HumanDecisionAuthority(actor=invalidated_by),
        note=reason,
        related_refs=list(invalidated_by_refs or ()),
    )
    services.runs.publish_content(prepared.publication)
    return prepared.decision


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
        services=sqlite_project_services(tmp_path),
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

from __future__ import annotations

from pathlib import Path

from scopecat.analysis.service import AnalysisOutput, save_analysis
from scopecat.config.candidates import (
    CandidateConfig,
)
from scopecat.config.changes import (
    parameter_change_proposal_from_updates,
    prepare_parameter_change_approval,
)
from scopecat.config.parameters import replace_scalar_parameter
from scopecat.config.registry.ports import ConfigRegistryUnitOfWorkFactory
from scopecat.config.registry.records import ConfigRegistryEntry
from scopecat.config.registry.service import (
    ConfigRegistryMutationResult,
    _register_candidate_config_locked,
    _validate_entry_id,
    _validate_required_text,
    current_config_registry_generation,
    load_config_registry_entry_snapshot,
    register_and_activate_candidate_config,
)
from scopecat.kernel.quantity import Quantity
from scopecat.project_state import ProjectStateServices
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter_change import (
    ParameterChangeApprovalRecord,
)
from tests.testkit.runtime import sqlite_project_services
from tests.testkit.signal_testkit import execute_signal_run
from tests.testkit.workflow_fixtures import load_invocation


def load_config() -> ConfigProfileSnapshot:
    from tests.testkit.workflow_fixtures import load_config as load_workflow_config

    return load_workflow_config()


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
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
    entry_id: str,
    registered_by: str,
    run_id: str,
    proposal_id: str,
    note: str = "",
) -> ConfigRegistryEntry:
    """Register without activation for persistence tests."""

    _validate_entry_id(entry_id)
    _validate_required_text(registered_by, field="registered_by")
    _validate_required_text(run_id, field="run_id")
    _validate_required_text(proposal_id, field="proposal_id")
    with unit_of_work() as work:
        return _register_candidate_config_locked(
            work=work,
            entry_id=entry_id,
            registered_by=registered_by,
            run_id=run_id,
            proposal_id=proposal_id,
            note=note,
        ).entry


def activate_candidate_config(
    *,
    candidate: CandidateConfig,
    services: ProjectStateServices,
    entry_id: str | None = None,
    registered_by: str,
    operator: str,
    note: str = "",
    activation_note: str | None = None,
    expected_generation: int | None = None,
) -> ConfigRegistryMutationResult:
    generation = (
        current_config_registry_generation(unit_of_work=services.config_registry)
        if expected_generation is None
        else expected_generation
    )
    return register_and_activate_candidate_config(
        unit_of_work=services.config_registry,
        entry_id=entry_id,
        registered_by=registered_by,
        run_id=candidate.source_run_id,
        proposal_id=candidate.proposal_id,
        operator=operator,
        expected_generation=generation,
        note=note,
        activation_note=activation_note,
    )


def review_parameter_change_proposal(
    *,
    run_id: str,
    selector: str,
    services: ProjectStateServices,
    reviewer: str,
    note: str = "",
) -> ParameterChangeApprovalRecord:
    prepared = prepare_parameter_change_approval(
        run_id=run_id,
        selector=selector,
        services=services,
        actor=reviewer,
        note=note,
    )
    if prepared.publication is not None:
        services.runs.publish_content(prepared.publication)
    return prepared.approval


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

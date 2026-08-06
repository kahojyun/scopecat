from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol

import scopecat as sc
from scopecat.planning.catalog import InstrumentContractCatalog
from scopecat.records.config import config_content_hash, instrument_bindings
from scopecat.sdk.instruments import InstrumentProviderContext

from reference_lab.application import create_application
from reference_lab.backend import create_backend
from reference_lab.configuration import (
    EXAMPLE_ROOT,
    bootstrap_config,
)
from reference_lab.workflows.drag_beta_analysis import drag_beta_analysis
from reference_lab.workflows.drag_beta_experiment import drag_beta_experiment


class _DemoDaemon(Protocol):
    url: str


def test_demo_manifest_discovers_application_owned_bootstrap_config() -> None:
    project = sc.open_project(EXAMPLE_ROOT / "notebooks")
    application = project.load_application()

    assert project.root == EXAMPLE_ROOT
    assert project.application_spec == "reference_lab.application:create_application"
    assert project.instrument_backend_spec == "reference_lab.backend:create_backend"
    assert application.bootstrap_config is not None
    assert application.bootstrap_config() == bootstrap_config()


def test_demo_application_loads_selected_project_system(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    shutil.copytree(EXAMPLE_ROOT / "config", config_dir)
    virtual_lab_path = config_dir / "virtual-lab.json"
    virtual_lab_path.write_text(
        virtual_lab_path.read_text().replace(
            '"id": "reference_lab.virtual_lab"',
            '"id": "selected-project-virtual-lab"',
            1,
        )
    )

    application = create_application(tmp_path)

    assert application.build_experiment_system is not None
    assert application.bootstrap_config is not None
    selected_config = application.bootstrap_config()
    assert selected_config == bootstrap_config(config_dir)
    backend = create_backend(tmp_path)
    provider = backend.provider
    from reference_lab.provider import ReferenceLabProvider

    assert isinstance(provider, ReferenceLabProvider)
    described = provider.describe(
        InstrumentProviderContext(bindings=instrument_bindings(selected_config))
    )
    catalog = InstrumentContractCatalog(
        config_content_hash=config_content_hash(selected_config),
        provider_id=described.provider_id,
        instruments=described.instruments,
        problems=described.problems,
    )
    system = application.build_experiment_system(selected_config, catalog)
    assert system.instrument_catalog == catalog
    assert system.domain_compiler is not None


def test_drag_beta_candidate_accept_and_undo_round_trip_through_shared_daemon(
    demo_daemon: _DemoDaemon,
) -> None:
    with sc.open_project(EXAMPLE_ROOT).connect(demo_daemon.url) as lab:
        run = lab.prepare(drag_beta_experiment()).run(
            name="DRAG beta daemon round trip"
        )
        analysis = run.analyze(drag_beta_analysis())
        saved = analysis.save()
        candidate = analysis.candidate_config()
        accepted = lab.config.accept(
            candidate,
            note="accept the DRAG beta golden candidate",
        )
        restored = lab.config.undo(
            note="restore the default after the DRAG beta golden candidate",
        )

        assert run.request is not None
        assert run.request.display_name == "DRAG beta daemon round trip"
        assert (
            lab.run_operations.analysis(run.id, saved.record.id).analysis.title
            == "DRAG beta calibration"
        )
        assert [
            item.analysis.title for item in lab.run_operations.analyses(run.id).items
        ] == ["DRAG beta calibration"]

    with sc.open_project(EXAMPLE_ROOT).connect(demo_daemon.url) as observer:
        detail = observer.control.run_detail(run.id)
        measurements = observer.control.measurements(run.id)
        proposals = observer.config.proposals(run.id)
        registry = observer.config.registry()

    assert detail.control.state == "closed"
    assert detail.manifest.status == "completed"
    assert len(measurements.items) == 15
    [proposal] = analysis.parameter_proposals
    assert candidate.parameter_proposal == proposal
    assert proposals.items[0].approval is not None
    assert proposals.items[0].approval.actor == "operator"
    assert registry.activation == restored.activation
    assert registry.activation is not None
    assert registry.activation.entry_id != accepted.entry.id

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol

import scopecat as sc
from quantum_lab_demo import (
    EXAMPLE_ROOT,
    quantum_lab_application,
    quantum_lab_bootstrap_config,
)
from quantum_lab_demo.virtual_lab.provider import QuantumLabVirtualProvider
from quantum_lab_demo.workflows.drag_beta_analysis import analyze_drag_beta_run
from quantum_lab_demo.workflows.drag_beta_experiment import drag_beta_template


class _DemoDaemon(Protocol):
    url: str


def test_demo_manifest_discovers_application_owned_bootstrap_config() -> None:
    project = sc.open_project(EXAMPLE_ROOT / "notebooks")
    application = project.load_application()

    assert project.root == EXAMPLE_ROOT
    assert (
        project.application_spec
        == "quantum_lab_demo.application:quantum_lab_application"
    )
    assert application.bootstrap_config is not None
    assert application.bootstrap_config() == quantum_lab_bootstrap_config()


def test_demo_application_loads_selected_project_system(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    shutil.copytree(EXAMPLE_ROOT / "config", config_dir)
    virtual_lab_path = config_dir / "virtual-lab.json"
    virtual_lab_path.write_text(
        virtual_lab_path.read_text().replace(
            '"id": "quantum_lab_demo.virtual_lab"',
            '"id": "selected-project-virtual-lab"',
            1,
        )
    )

    application = quantum_lab_application(tmp_path)

    assert application.build_system is not None
    assert application.bootstrap_config is not None
    bootstrap_config = application.bootstrap_config()
    assert bootstrap_config == quantum_lab_bootstrap_config(config_dir)
    provider = application.build_system(bootstrap_config).provider
    assert isinstance(provider, QuantumLabVirtualProvider)
    assert provider.profile.id == "selected-project-virtual-lab"


def test_drag_beta_candidate_accept_and_undo_round_trip_through_shared_daemon(
    demo_daemon: _DemoDaemon,
) -> None:
    with sc.open_project(EXAMPLE_ROOT).connect(demo_daemon.url) as lab:
        run = lab.prepare(drag_beta_template()).run(name="DRAG beta daemon round trip")
        result = analyze_drag_beta_run(run)
        saved = result.analysis.save()
        candidate = result.analysis.candidate_config()
        accepted = lab.config.accept(
            candidate,
            note="accept the DRAG beta golden candidate",
        )
        restored = lab.config.undo(
            note="restore the default after the DRAG beta golden candidate",
        )

        assert run.request is not None
        assert run.request.metadata["name"] == "DRAG beta daemon round trip"
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
    assert candidate.proposal_id == result.proposal_id
    assert proposals.items[0].approval is not None
    assert proposals.items[0].approval.actor == "operator"
    assert registry.active_state == restored.active_state
    assert registry.active_state is not None
    assert registry.active_state.active_entry_id != accepted.entry.id

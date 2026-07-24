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
from quantum_lab_demo.workflows.readout_frequency import readout_frequency_template


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


def test_demo_execution_round_trips_through_shared_daemon(
    demo_daemon: _DemoDaemon,
) -> None:
    with sc.open_project(EXAMPLE_ROOT).connect(demo_daemon.url) as lab:
        run = lab.prepare(readout_frequency_template(qubit="q0")).run(
            name="daemon client round trip"
        )
        attachment = run.attach(
            key="notebook-note",
            text="reviewed in notebook",
            filename="review.md",
        )
        saved = (
            run.analysis("fit review")
            .artifact(
                title="fit result",
                kind="fit_result",
                artifact_id="fit-result",
                json_content={"accepted": True},
            )
            .save()
        )

        assert run.request is not None
        assert run.request.metadata["name"] == "daemon client round trip"
        assert attachment.filename == "review.md"
        assert run.data().text("notebook-note").content == "reviewed in notebook\n"
        assert run.data().json("fit-result").content == {"accepted": True}
        assert (
            lab.run_operations.analysis(run.id, saved.record.id).analysis.title
            == "fit review"
        )
        assert [
            item.analysis.title for item in lab.run_operations.analyses(run.id).items
        ] == ["fit review"]

    with sc.open_project(EXAMPLE_ROOT).connect(demo_daemon.url) as observer:
        detail = observer.control.run_detail(run.id)
        measurements = observer.control.measurements(run.id)

    assert detail.control.state == "terminal"
    assert detail.manifest.status == "completed"
    assert len(measurements.items) == 5

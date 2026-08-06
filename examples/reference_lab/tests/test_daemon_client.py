from __future__ import annotations

import shutil
from pathlib import Path

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


def test_reference_lab_manifest_discovers_application_bootstrap_config() -> None:
    project = sc.open_project(EXAMPLE_ROOT / "notebooks")
    application = project.load_application()

    assert project.root == EXAMPLE_ROOT
    assert project.application_spec == "reference_lab.application:create_application"
    assert project.instrument_backend_spec == "reference_lab.backend:create_backend"
    assert application.bootstrap_config is not None
    assert application.bootstrap_config() == bootstrap_config()


def test_reference_lab_application_loads_selected_project_system(
    tmp_path: Path,
) -> None:
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

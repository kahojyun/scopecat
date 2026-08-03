"""Source-controlled files for a runnable local lab project."""

from __future__ import annotations

from pathlib import Path

_PROJECT_FILES = {
    "scopecat.toml": """\
[lab]
application = "scopecat_lab.application:create_application"
instrument_backend = "scopecat_lab.backend:create_backend"
""",
    "src/scopecat_lab/__init__.py": '''\
"""User-owned composition for this Scopecat project."""
''',
    "src/scopecat_lab/configuration.py": '''\
"""Editable Python source for the project's initial configuration."""

from __future__ import annotations

import scopecat as sc
from scopecat.kernel.entity import EntityRef
from scopecat.records.config import (
    ConfigProfileSnapshot,
    InstrumentRegistry,
    SystemSpec,
    Topology,
    snapshot_config_profile,
)
from scopecat.records.parameter import (
    ParameterCatalog,
    ParameterDefinition,
    ParameterSnapshot,
    ScalarParameterValue,
)

DEFAULT_REPETITIONS = 128


def bootstrap_config() -> ConfigProfileSnapshot:
    """Build the default config used only while the daemon registry is empty."""

    return snapshot_config_profile(
        profile_id="default",
        system=SystemSpec(
            id="default-system",
            primary_entity_id="sample",
            topology=Topology(
                entities=[EntityRef(id="sample", kind="sample")],
            ),
            instrument_registry=InstrumentRegistry(instruments=[]),
            domain_target=None,
            parameter_catalog=ParameterCatalog(
                id="parameters",
                definitions=(
                    ParameterDefinition(
                        id="repetitions",
                        value_type=sc.ScalarType(sc.IntType(minimum=1)),
                        description="Default number of repeated acquisitions.",
                    ),
                ),
            ),
        ),
        parameter_snapshot=ParameterSnapshot(
            id="default-values",
            values=(
                ScalarParameterValue(
                    id="repetitions",
                    value=DEFAULT_REPETITIONS,
                ),
            ),
        ),
    )


__all__ = ["bootstrap_config"]
''',
    "src/scopecat_lab/application.py": '''\
"""Daemon and notebook composition for this project."""

from __future__ import annotations

from pathlib import Path

from scopecat.application import LabApplication

from .configuration import bootstrap_config


def create_application(_project_root: Path) -> LabApplication:
    """Compose version-controlled config and local execution capabilities."""

    return LabApplication(bootstrap_config=bootstrap_config)


__all__ = ["create_application"]
''',
    "src/scopecat_lab/backend.py": '''\
"""Worker-only instrument backend composition for this project."""

from __future__ import annotations

from pathlib import Path

from scopecat.sdk.instruments import (
    DriverCatalog,
    InstrumentBackend,
    InstrumentConnectionContext,
    InstrumentDriver,
    InstrumentProviderContext,
    InstrumentProviderDescription,
)


class LocalProvider:
    """Let the starter experiment run before real instruments are connected."""

    provider_id = "scopecat-lab.local"
    driver_catalog = DriverCatalog(provider_id=provider_id)

    def describe(
        self,
        _context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        return InstrumentProviderDescription(provider_id=self.provider_id)

    def connect(
        self,
        context: InstrumentConnectionContext,
    ) -> InstrumentDriver:
        raise RuntimeError(f"no instrument is configured: {context.binding.id}")


def create_backend(_project_root: Path) -> InstrumentBackend:
    provider = LocalProvider()
    return InstrumentBackend(
        provider=provider,
        driver_catalog=provider.driver_catalog,
    )


__all__ = ["create_backend"]
''',
    "notebooks/01_first_run.py": '''\
"""Run the smallest experiment through the project daemon."""

from __future__ import annotations

from pathlib import Path

import scopecat as sc

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@sc.experiment_factory(id="scopecat_lab.first_run", kind="first_run")
def first_run(experiment: sc.ExperimentContext) -> None:
    """Close the daemon, notebook, history, and GUI loop without hardware."""

    del experiment


# %%
project = sc.open_project(PROJECT_ROOT)
with project.connect() as lab:
    run = lab.run(first_run(), name="First run")
    summary = {"run_id": run.id, "status": run.manifest.status}

print(summary)
''',
}


def scaffold_paths(root: Path) -> tuple[Path, ...]:
    """Return every file owned by project initialization."""

    return tuple(root / relative_path for relative_path in _PROJECT_FILES)


def write_project_scaffold(root: Path) -> None:
    """Write a preflighted scaffold without replacing existing files."""

    for relative_path, content in _PROJECT_FILES.items():
        destination = root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


__all__ = ["scaffold_paths", "write_project_scaffold"]

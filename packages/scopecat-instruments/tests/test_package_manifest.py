from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import ClassVar, Protocol, cast

from scopecat_instruments.package_manifest import PACKAGE_MANIFEST

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GENERATOR = REPOSITORY_ROOT / "scripts" / "generate_instrument_clients.py"
_DRIVER_MODULES = (
    "scopecat_instruments.drivers.e5080b",
    "scopecat_instruments.drivers.gs200",
    "scopecat_instruments.drivers.lakeshore372",
    "scopecat_instruments.drivers.sgs100a",
    "scopecat_instruments.virtual.drivers",
)


class _RegisteredImplementation(Protocol):
    implementation_id: ClassVar[str]
    implementation_version: ClassVar[str]


def test_provider_import_does_not_load_driver_implementations() -> None:
    runtime_forbidden = (*_DRIVER_MODULES, "scopecat.sdk.instruments.client_codegen")
    script = (
        "import sys\n"
        "from scopecat_instruments.provider import ConfiguredInstrumentProvider\n"
        "ConfiguredInstrumentProvider()\n"
        f"forbidden = {runtime_forbidden!r}\n"
        "loaded = [name for name in forbidden if name in sys.modules]\n"
        "assert not loaded, loaded\n"
    )

    subprocess.run(  # noqa: S603 - fixed interpreter and local test source
        [sys.executable, "-c", script],
        check=True,
    )


def test_driver_package_exports_follow_manifest_without_loading_drivers() -> None:
    script = (
        "import sys\n"
        "import scopecat_instruments.drivers as real\n"
        "import scopecat_instruments.virtual as virtual\n"
        "from scopecat_instruments.package_manifest import PACKAGE_MANIFEST\n"
        "real_prefix = 'scopecat_instruments.drivers.'\n"
        "virtual_prefix = 'scopecat_instruments.virtual.'\n"
        "real_expected = sorted(\n"
        "    item.implementation.qualname\n"
        "    for item in PACKAGE_MANIFEST.drivers\n"
        "    if item.implementation.module.startswith(real_prefix)\n"
        ")\n"
        "virtual_expected = sorted((\n"
        "    'VirtualLabWorld',\n"
        "    *(item.implementation.qualname\n"
        "      for item in PACKAGE_MANIFEST.drivers\n"
        "      if item.implementation.module.startswith(virtual_prefix)),\n"
        "))\n"
        "assert real.__all__ == real_expected\n"
        "assert virtual.__all__ == virtual_expected\n"
        f"forbidden = {_DRIVER_MODULES!r}\n"
        "loaded = [name for name in forbidden if name in sys.modules]\n"
        "assert not loaded, loaded\n"
    )

    subprocess.run(  # noqa: S603 - fixed interpreter and local test source
        [sys.executable, "-c", script],
        check=True,
    )


def test_resolving_one_driver_does_not_load_sibling_implementations() -> None:
    forbidden = tuple(
        module for module in _DRIVER_MODULES if not module.endswith(".gs200")
    )
    script = (
        "import sys\n"
        "from scopecat_instruments.package_manifest import YOKOGAWA_GS200_DRIVER\n"
        "YOKOGAWA_GS200_DRIVER.implementation.resolve()\n"
        f"forbidden = {forbidden!r}\n"
        "loaded = [name for name in forbidden if name in sys.modules]\n"
        "assert not loaded, loaded\n"
    )

    subprocess.run(  # noqa: S603 - fixed interpreter and local test source
        [sys.executable, "-c", script],
        check=True,
    )


def test_generator_does_not_resolve_driver_implementation_symbols() -> None:
    script = (
        "import runpy\n"
        "import sys\n"
        f"generator = {str(GENERATOR)!r}\n"
        "sys.argv = [generator, '--check']\n"
        "runpy.run_path(generator, run_name='__main__')\n"
        f"forbidden = {_DRIVER_MODULES!r}\n"
        "loaded = [name for name in forbidden if name in sys.modules]\n"
        "assert not loaded, loaded\n"
    )

    subprocess.run(  # noqa: S603 - fixed interpreter and local test source
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        check=True,
    )


def test_every_driver_registration_resolves_its_declared_implementation() -> None:
    assert len(PACKAGE_MANIFEST.drivers) == 8

    for registration in PACKAGE_MANIFEST.drivers:
        implementation = cast(
            "type[_RegisteredImplementation]",
            registration.implementation.resolve(),
        )

        assert isinstance(implementation, type)
        assert implementation.implementation_id == registration.id
        assert (
            implementation.implementation_version == registration.implementation_version
        )

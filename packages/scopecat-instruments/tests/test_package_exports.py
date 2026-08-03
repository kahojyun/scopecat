from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import cast

import scopecat_instruments as instrument_package
import scopecat_instruments.clients as client_module
import scopecat_instruments.states as state_module

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_LAZY_EXPORT_CHECK = """
import sys
from importlib import import_module

import scopecat_instruments as instruments

public_export_modules = instruments.__dict__["_PUBLIC_EXPORT_MODULES"]

lazy_modules = {
    "scopecat_instruments.clients",
    "scopecat_instruments.provider",
    "scopecat_instruments.states",
}
assert lazy_modules.isdisjoint(sys.modules)
assert instruments.__all__ == sorted(public_export_modules)
assert set(instruments.__all__) <= set(dir(instruments))

for name, module in public_export_modules.items():
    exported = getattr(instruments, name)
    assert exported is getattr(import_module(module), name)
    assert instruments.__dict__[name] is exported

assert len(dir(instruments)) == len(set(dir(instruments)))

try:
    getattr(instruments, "not_a_public_instrument_export")
except AttributeError:
    pass
else:
    raise AssertionError("unknown package export did not raise AttributeError")
"""


def test_package_export_routes_match_generated_module_exports() -> None:
    expected = {
        "ConfiguredInstrumentProvider": "scopecat_instruments.provider",
        **dict.fromkeys(client_module.__all__, "scopecat_instruments.clients"),
        **dict.fromkeys(state_module.__all__, "scopecat_instruments.states"),
    }

    assert set(client_module.__all__).isdisjoint(state_module.__all__)
    public_export_modules = cast(
        "dict[str, str]",
        instrument_package.__dict__["_PUBLIC_EXPORT_MODULES"],
    )

    assert expected == public_export_modules


def test_package_exports_are_lazy_and_consistent() -> None:
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and local source
        [sys.executable, "-c", _LAZY_EXPORT_CHECK],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr

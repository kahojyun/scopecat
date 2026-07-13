from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.testkit.no_live_imports import NO_LIVE_IMPORT_EXERCISES, Exercise

FORBIDDEN_IMPORTS = {
    "pyvisa",
    "serial",
    "labrad",
    "requests",
    "numpy",
    "scipy",
    "pandas",
}


@pytest.mark.parametrize("exercise", NO_LIVE_IMPORT_EXERCISES)
def test_core_boundaries_do_not_import_live_or_scientific_dependencies(
    exercise: Exercise,
    tmp_path: Path,
) -> None:
    before = FORBIDDEN_IMPORTS.intersection(sys.modules)

    exercise(tmp_path)

    after = FORBIDDEN_IMPORTS.intersection(sys.modules)
    assert after == before

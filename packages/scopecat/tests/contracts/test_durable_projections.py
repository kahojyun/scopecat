from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from scopecat.compiler.frontend.environment import build_config_environment
from scopecat.compiler.frontend.resolution import (
    compile_invocation,
    resolve_compiled_invocation,
)
from scopecat.records.run_request import RunRequest
from tests.testkit.workflow_fixtures import load_config, load_invocation

FIXTURE_DIR = Path(__file__).with_name("fixtures")


def _golden(name: str) -> dict[str, Any]:
    return cast(
        "dict[str, Any]",
        json.loads((FIXTURE_DIR / name).read_text()),
    )


def _canonical_request(project_root: Path) -> RunRequest:
    """Project the canonical simple-scan request through the real pipeline."""

    del project_root
    compiled_invocation = compile_invocation(load_invocation())
    environment = build_config_environment(load_config())
    resolved = resolve_compiled_invocation(
        compiled_invocation,
        environment=environment,
    )
    assert resolved.environment is environment
    return compiled_invocation.request


def test_run_request_projector_matches_golden_and_round_trips(
    tmp_path: Path,
) -> None:
    golden = _golden("run-request.json")
    request = _canonical_request(tmp_path)

    restored = RunRequest.model_validate_json(json.dumps(golden))

    assert request.model_dump(mode="json") == golden
    assert restored == request


@pytest.mark.parametrize(
    "corruption",
    [
        "unknown_scan_kind",
        "missing_scan_values",
    ],
)
def test_corrupt_run_request_is_rejected(
    corruption: str,
) -> None:
    request = deepcopy(_golden("run-request.json"))
    if corruption == "unknown_scan_kind":
        request["scans"][0]["kind"] = "compute"
    elif corruption == "missing_scan_values":
        del request["scans"][0]["points"]
    else:  # pragma: no cover - parametrization is closed above
        raise AssertionError(corruption)

    with pytest.raises(ValidationError):
        RunRequest.model_validate(request)

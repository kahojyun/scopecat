from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from scopecat.compiler.bind import bind_program
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.config.environment import build_config_environment
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
    resolved = bind_program(compiled_invocation.program, environment)
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

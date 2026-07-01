from __future__ import annotations

import scopecat as sc
import scopecat.authoring as authoring
import scopecat.diagnostics as diagnostics
import scopecat.execution as execution
import scopecat.results as results
import scopecat.workflows as workflows


def test_user_facing_facades_expose_entry_points() -> None:
    assert callable(sc.open)
    assert sc.Run is sc.RunHandle
    assert callable(authoring.sweep)
    assert callable(execution.execute_dry_run)
    assert callable(workflows.register_and_activate_candidate_config)
    assert hasattr(results, "MeasurementRecord")
    assert {"severity", "code"}.issubset(diagnostics.Diagnostic.model_fields)

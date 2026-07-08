from __future__ import annotations

import scopecat as sc
import scopecat.diagnostics as diagnostics
import scopecat.results as results


def test_user_facing_facades_expose_entry_points() -> None:
    assert callable(sc.open)
    assert sc.Run is sc.RunHandle
    assert callable(sc.module)
    assert callable(sc.template)
    assert callable(sc.around)
    assert callable(sc.var)
    assert callable(sc.param)
    assert callable(sc.table_param)
    assert hasattr(results, "MeasurementRecord")
    assert {"severity", "code"}.issubset(diagnostics.Diagnostic.model_fields)

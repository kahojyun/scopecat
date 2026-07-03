from __future__ import annotations

from collections.abc import Iterable

from scopecat.diagnostics import Diagnostic, DiagnosticSeverity

CORE_DIAGNOSTIC_DEFAULT_SEVERITY: dict[str, DiagnosticSeverity] = {
    "empty_run_comparison_input": "error",
    "invalid_run_comparison": "error",
    "invalid_run_comparison_input": "error",
    "missing_run_comparison_dataset_schema": "error",
    "missing_run_comparison_input": "error",
    "run_comparison_ambiguous_primary_observable": "error",
    "run_comparison_invalid_id": "error",
    "run_comparison_measurement_mismatch": "error",
    "run_comparison_missing_observable": "error",
    "run_comparison_point_mismatch": "error",
    "run_comparison_primary_observable_mismatch": "error",
    "run_comparison_unit_mismatch": "error",
}


def diagnostic_codes(diagnostics: Iterable[Diagnostic]) -> list[str]:
    return [diagnostic.code for diagnostic in diagnostics]


def assert_diagnostic(
    diagnostic: Diagnostic,
    code: str,
    *,
    path: str | None = None,
    severity: DiagnosticSeverity | None = None,
) -> None:
    assert code in CORE_DIAGNOSTIC_DEFAULT_SEVERITY
    assert diagnostic.code == code
    assert diagnostic.severity == (severity or CORE_DIAGNOSTIC_DEFAULT_SEVERITY[code])
    if path is not None:
        assert diagnostic.path == path


__all__ = [
    "CORE_DIAGNOSTIC_DEFAULT_SEVERITY",
    "assert_diagnostic",
    "diagnostic_codes",
]

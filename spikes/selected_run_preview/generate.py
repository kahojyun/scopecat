"""Generate a tiny plot-spec preview from a selected-run handoff fixture.

This module is a validation spike, not product code or a durable data schema.
It intentionally supports one public-safe 1D CSV fixture with one sweep axis
and multiple declared measured responses.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

DECISIONS_NOT_EARNED = [
    "general data schema",
    "automatic schema inference",
    "plot rendering",
    "dataframe dependency choice",
    "2D scans, ragged scans, traces, complex arrays, NPZ/HDF5, or backend readers",
    "fit quality, uncertainty, or scientific validity",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _column_by_role(columns: list[dict[str, str]], role: str) -> list[dict[str, str]]:
    return [column for column in columns if column["role"] == role]


def _numeric(value: str) -> int | float | str:
    try:
        as_float = float(value)
    except ValueError:
        return value
    return int(as_float) if as_float.is_integer() else as_float


def _format_list(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def _format_cell(value: Any) -> str:
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def generate_preview(fixture_root: Path) -> dict[str, Any]:
    source = load_json(fixture_root / "handoff-input.json")
    selected = source["selected_run"]
    figure = source["figure_readiness"]
    source_file = selected["source_file"]
    source_path = fixture_root / source_file
    rows = read_csv_rows(source_path)

    declared_columns = figure["source_columns"]
    declared_names = [column["name"] for column in declared_columns]
    csv_columns = list(rows[0].keys()) if rows else []
    missing_columns = [name for name in declared_names if name not in csv_columns]
    extra_columns = [name for name in csv_columns if name not in declared_names]

    sweep_axes = _column_by_role(declared_columns, "sweep_axis")
    measured = _column_by_role(declared_columns, "measured_response")
    held = _column_by_role(declared_columns, "held_condition")
    validation_failures = []
    if missing_columns:
        validation_failures.append("declared columns missing from source header")
    if not sweep_axes:
        validation_failures.append("no declared sweep axis")
    if not measured:
        validation_failures.append("no declared measured response")
    validation_status = "fail" if validation_failures else "pass"

    preview_columns: list[str] = []
    preview_rows: list[dict[str, int | float | str]] = []
    plot_candidates: list[dict[str, Any]] = []
    caption_stub = "Preview unavailable because declared source-column validation failed."

    if validation_status == "pass":
        primary_x = sweep_axes[0]
        preview_columns = [
            primary_x["name"],
            *[column["name"] for column in measured],
            *[column["name"] for column in held],
        ]
        preview_rows = [{name: _numeric(row[name]) for name in preview_columns} for row in rows[:5]]

        plot_candidates = [
            {
                "title": f"{selected['experiment_label']} preview: {column['name']}",
                "source": source_file,
                "x": {
                    "column": primary_x["name"],
                    "unit": primary_x["unit"],
                    "role": primary_x["role"],
                },
                "y": {
                    "column": column["name"],
                    "unit": column["unit"],
                    "role": column["role"],
                },
                "held_conditions": [
                    {
                        "column": held_column["name"],
                        "unit": held_column["unit"],
                        "value": _numeric(rows[0][held_column["name"]]) if rows else None,
                    }
                    for held_column in held
                ],
                "rows_used": len(rows),
                "boundary_note": (
                    "Plot-spec-ready display preview only; source export remains "
                    "separate; no fit, uncertainty, or scientific validation."
                ),
            }
            for column in measured
        ]

        caption_stub = (
            f"{selected['experiment_label']} for target {selected['target']}: "
            f"{', '.join(column['name'] for column in measured)} versus "
            f"{primary_x['name']} from selected source run {selected['legacy_data_id']} "
            f"({selected['run_started_at']}). "
            "Calibration notes, fit result, and uncertainty are missing."
        )

    return {
        "preview_id": f"{source['fixture_id']}.preview.expected",
        "status": "expected_preview_output",
        "source_fixture": "handoff-input.json",
        "selected_run": {
            "legacy_data_id": selected["legacy_data_id"],
            "experiment_label": selected["experiment_label"],
            "experiment_type": selected["experiment_type"],
            "target": selected["target"],
            "source_file": source_file,
        },
        "column_validation": {
            "status": validation_status,
            "declared_columns": declared_names,
            "source_columns": csv_columns,
            "missing_declared_columns": missing_columns,
            "extra_source_columns": extra_columns,
            "failures": validation_failures,
            "validated": [
                "declared column names against source CSV header",
                "presence of at least one declared sweep axis",
                "presence of at least one declared measured response",
            ],
            "not_validated": [
                "role semantic correctness",
                "unit correctness",
                "held-condition constancy",
                "numeric suitability",
                "scientific validity",
            ],
        },
        "preview_table": {
            "row_count": len(rows),
            "displayed_row_count": len(preview_rows),
            "columns": preview_columns,
            "rows": preview_rows,
        },
        "plot_spec": plot_candidates[0] if plot_candidates else None,
        "plot_candidates": plot_candidates,
        "caption_stub": caption_stub,
        "warnings": [],
        "boundary_notes": [
            "This output is plot-spec preview data, not a rendered plot.",
            "Column roles come from fixture metadata; the spike does not infer a general schema.",
            "Preview does not provide fit quality, uncertainty, or scientific validity.",
        ],
        "future_scan_shape_backlog": [
            "2d_grid_csv",
            "trace_per_point",
            "complex_iq",
            "ragged_steps",
            "npz_companion",
            "derived_table",
        ],
        "decisions_not_earned": DECISIONS_NOT_EARNED,
    }


def generate_review(preview: dict[str, Any]) -> str:
    selected = preview["selected_run"]
    validation = preview["column_validation"]
    table = preview["preview_table"]
    spec = preview["plot_spec"]
    candidates = preview["plot_candidates"]
    column_names = table["columns"]

    lines = [
        "# Expected Selected Run Preview",
        "",
        "## Status",
        "",
        "Expected output for the selected-run preview spike. This is not a product",
        "plotting UI, data schema contract, or report.",
        "",
        "## Source",
        "",
        f"- selected run: `{selected['legacy_data_id']}`",
        f"- experiment: `{selected['experiment_label']}`",
        f"- target: `{selected['target']}`",
        f"- source file: `{selected['source_file']}`",
        "",
        "## Column Validation",
        "",
        f"- status: `{validation['status']}`",
        f"- declared columns: `{_format_list(validation['declared_columns'])}`",
        f"- source columns: `{_format_list(validation['source_columns'])}`",
        f"- missing declared columns: `{_format_list(validation['missing_declared_columns'])}`",
        f"- extra source columns: `{_format_list(validation['extra_source_columns'])}`",
        f"- failures: `{_format_list(validation['failures'])}`",
        f"- validated: `{'; '.join(validation['validated'])}`",
        f"- not validated: `{'; '.join(validation['not_validated'])}`",
        "",
        "## Preview Table",
        "",
        f"Rows: `{table['displayed_row_count']}` of `{table['row_count']}`.",
        "",
    ]

    if column_names:
        lines.append("| " + " | ".join(column_names) + " |")
        lines.append("| " + " | ".join("---" for _ in column_names) + " |")
    else:
        lines.append("Preview rows unavailable.")

    for row in table["rows"]:
        cells = [f"`{_format_cell(row[name])}`" for name in column_names]
        lines.append("| " + " | ".join(cells) + " |")

    lines.extend(
        [
            "",
            "## Plot Spec",
            "",
        ]
    )

    if spec is None:
        lines.append("Plot spec unavailable.")
    else:
        lines.extend(
            [
                f"- title: `{spec['title']}`",
                f"- x: `{spec['x']['column']}` (`{spec['x']['unit']}`)",
                f"- y: `{spec['y']['column']}` (`{spec['y']['unit']}`)",
                f"- held condition: `bias_v = {spec['held_conditions'][0]['value']:.3f} V`",
                f"- rows used: `{spec['rows_used']}`",
                f"- boundary note: {spec['boundary_note']}",
            ]
        )

    lines.extend(
        [
            "",
            "## Plot Candidates",
            "",
        ]
    )

    if candidates:
        lines.extend(["| X | Y | Source | Boundary note |", "| --- | --- | --- | --- |"])
    else:
        lines.append("Plot candidates unavailable.")

    for candidate in candidates:
        lines.append(
            f"| `{candidate['x']['column']}` | `{candidate['y']['column']}` | "
            f"`{candidate['source']}` | {candidate['boundary_note']} |"
        )

    lines.extend(
        [
            "",
            "## Caption Stub",
            "",
            preview["caption_stub"],
            "",
            "## Boundary Notes",
            "",
            "- This output is plot-spec preview data, not a rendered plot.",
            "- Column roles come from fixture metadata; the spike does not infer a",
            "  general schema.",
            "- Preview does not provide fit quality, uncertainty, or scientific validity.",
            "",
            "## Future Scan Shape Backlog",
            "",
            "- `2d_grid_csv`",
            "- `trace_per_point`",
            "- `complex_iq`",
            "- `ragged_steps`",
            "- `npz_companion`",
            "- `derived_table`",
        ]
    )
    return "\n".join(lines) + "\n"

"""Generate a selected-run handoff summary from a tiny public-safe fixture.

This module is a validation spike, not product code or a durable schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DECISIONS_NOT_EARNED = [
    "final package format",
    "complete reader/export API",
    "central storage or sync",
    "report generation",
    "complete reanalysis",
    "user/domain conclusions or reproducibility",
    "related-but-not-exported run context",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def openability(root: Path, rel_path: str) -> str:
    return "present" if (root / rel_path).exists() else "missing"


def read_parameter_context(root: Path, rel_path: str) -> dict[str, Any]:
    snapshot = load_json(root / rel_path)
    params = snapshot.get("parameters", {})
    q_params = params.get("qA", {})
    setup = params.get("setup", {})
    return {
        "setup": setup.get("fridge"),
        "sample": setup.get("sample"),
        "relevant_parameters": {
            "readout_frequency_ghz": q_params.get("readout_frequency_ghz"),
            "drive_frequency_ghz": q_params.get("drive_frequency_ghz"),
            "rabi_amp": q_params.get("rabi_amp"),
        },
    }


def generate_manifest(fixture_root: Path) -> dict[str, Any]:
    source = load_json(fixture_root / "handoff-input.json")
    selected = source["selected_run"]
    legacy_location = source["legacy_source_location"]
    linked = source["linked_context"]
    figure = source["figure_readiness"]
    parameter_path = linked["parameter_snapshot"]
    parameter_context = read_parameter_context(fixture_root, parameter_path)

    companions = [
        {
            "path": item["path"],
            "relation": item["relation"],
            "openability": openability(fixture_root, item["path"]),
        }
        for item in linked["companions"]
    ]
    derived_artifacts = [
        {
            "path": item["path"],
            "relation": item["source_relation"],
            "openability": openability(fixture_root, item["path"]),
            "boundary_note": "Trace link only. Not recomputed from source data.",
        }
        for item in linked["derived_artifacts"]
    ]

    selected_run = {
        "role": "selected",
        "legacy_data_id": selected["legacy_data_id"],
        "experiment_label": selected["experiment_label"],
        "experiment_type": selected["experiment_type"],
        "target": selected["target"],
        "run_started_at": selected["run_started_at"],
        "source_reference": {
            "session": legacy_location["session"],
            "encoded_filename": selected["encoded_filename"],
            "source_file": selected["source_file"],
            "export_source": selected["export_source"],
        },
        "no_silent_transform": selected["no_silent_transform"],
        "transform_policy": selected["transform_policy"],
        "selection_rationale": selected["selection_rationale"],
        "links": {
            "parameter_snapshot": {
                "path": parameter_path,
                "openability": openability(fixture_root, parameter_path),
            },
            "companions": companions,
            "derived_artifacts": derived_artifacts,
        },
    }

    source_columns = figure["source_columns"]
    candidate_plots = []
    for plot in figure["candidate_plots"]:
        plot_output = dict(plot)
        for column in source_columns:
            if column["name"] == plot.get("x"):
                plot_output["x_unit"] = column.get("unit")
            if column["name"] == plot.get("y"):
                plot_output["y_unit"] = column.get("unit")
        candidate_plots.append(plot_output)

    figure_readiness = {
        "status": "partial",
        "experiment_label": selected["experiment_label"],
        "experiment_type": selected["experiment_type"],
        "target": selected["target"],
        "run_started_at": selected["run_started_at"],
        "measurement_context": {
            "session": legacy_location["session"],
            "setup": parameter_context["setup"],
            "sample": parameter_context["sample"],
            "held_condition": {
                "bias_v": {
                    "value": figure["measurement_context"]["held_condition"]["bias_v"],
                    "unit": "V",
                }
            },
            "relevant_parameters": parameter_context["relevant_parameters"],
        },
        "source_columns": source_columns,
        "candidate_plots": candidate_plots,
        "missing_for_group_meeting": figure["missing_for_group_meeting"],
        "boundary_note": "Enough to draft a figure candidate, not enough for user/domain conclusions.",
    }

    openability_paths = [
        selected["source_file"],
        parameter_path,
        *[item["path"] for item in linked["companions"]],
        *[item["path"] for item in linked["derived_artifacts"]],
    ]
    present_paths = [
        path for path in openability_paths if openability(fixture_root, path) == "present"
    ]
    missing_paths = [
        path for path in openability_paths if openability(fixture_root, path) == "missing"
    ]
    missing_companion_paths = [
        item["path"] for item in companions if item["openability"] == "missing"
    ]

    warnings = [
        {
            "code": "local_only_path",
            "subject": "legacy_source_location.local_path",
            "message": "Original local path is redaction-sensitive and not portable.",
            "public_safe_value": legacy_location["display_path"],
        }
    ]
    if missing_companion_paths:
        warnings.append(
            {
                "code": "missing_companion",
                "subject": missing_companion_paths[0],
                "message": "Referenced companion is absent from the handoff fixture.",
            }
        )
    warnings.append(
        {
            "code": "figure_readiness_partial",
            "subject": f"legacy_data_id:{selected['legacy_data_id']}",
            "message": "The handoff includes experiment label, measured columns, context, and plot candidates, but calibration notes, fit results, uncertainty, and user selection rationale are missing.",
        }
    )

    return {
        "manifest_id": f"{source['fixture_id']}.expected",
        "status": "expected_validation_output",
        "source_fixture": "handoff-input.json",
        "selected_runs": [selected_run],
        "figure_readiness": figure_readiness,
        "warnings": warnings,
        "boundary_notes": [
            "Selected source data should not be silently compressed, converted, filtered, or otherwise transformed during export. This fixture does not define a final checksum or package contract.",
            "The handoff preserves where the selected data was exported from using a public-safe source reference.",
            "Source data, copied parameter context, companion artifact, and derived artifact are represented as different kinds of handoff material.",
            "Derived artifact relations are linked by fixture declaration; this fixture does not recompute analysis.",
            "Selection indicates handoff intent only, not run quality or reproducibility.",
        ],
        "openability_summary": {
            "present": present_paths,
            "missing": missing_paths,
            "redacted_or_local_only": ["legacy_source_location.local_path"],
        },
        "decisions_not_earned": DECISIONS_NOT_EARNED,
    }


def _ghz(value: float) -> str:
    return f"{value:.3f} GHz"


def generate_review(manifest: dict[str, Any]) -> str:
    selected = manifest["selected_runs"][0]
    source_ref = selected["source_reference"]
    figure = manifest["figure_readiness"]
    context = figure["measurement_context"]
    params = context["relevant_parameters"]
    held_bias = context["held_condition"]["bias_v"]
    parameter_path = selected["links"]["parameter_snapshot"]["path"]
    companion_present = selected["links"]["companions"][0]["path"]
    companion_missing = selected["links"]["companions"][1]["path"]
    derived_path = selected["links"]["derived_artifacts"][0]["path"]
    warnings = {item["code"]: item for item in manifest["warnings"]}

    lines = [
        "# Expected Selected Run Handoff Review",
        "",
        "## Status",
        "",
        "Expected reviewer-facing output for the synthetic minimal fixture. This is not",
        "a product UI, package format, or public documentation contract.",
        "",
        "## Selection",
        "",
        f"Selected run: legacy data ID `{selected['legacy_data_id']}`.",
        "",
        "Source reference:",
        "",
        f"- session: `{source_ref['session']}`",
        f"- encoded filename: `{source_ref['encoded_filename']}`",
        "- fixture source file:",
        f"  `{source_ref['source_file']}`",
        "- export source:",
        f"  `{source_ref['export_source']}`",
        "",
        "Selection rationale:",
        "",
        f"Run `{selected['legacy_data_id']}` was chosen as the candidate to hand off for downstream contrast",
        "analysis. This is a handoff choice, not a claim that the run is scientifically",
        "validated.",
        "",
        "## Figure Readiness",
        "",
        f"Status: {figure['status']}.",
        "",
        "Experiment:",
        "",
        f"- label: `{figure['experiment_label']}`",
        f"- type: `{figure['experiment_type']}`",
        f"- target: `{figure['target']}`",
        f"- run started at: `{figure['run_started_at']}`",
        f"- session: `{context['session']}`",
        f"- setup: `{context['setup']}`",
        f"- sample: `{context['sample']}`",
        "",
        "Relevant parameter context:",
        "",
        f"- readout frequency: `{_ghz(params['readout_frequency_ghz'])}`",
        f"- drive frequency: `{_ghz(params['drive_frequency_ghz'])}`",
        f"- Rabi amplitude parameter: `{params['rabi_amp']}`",
        f"- held bias condition: `{held_bias['value']:.3f} {held_bias['unit']}`",
        "",
        "Source columns:",
        "",
        "| Column | Role | Unit |",
        "| --- | --- | --- |",
    ]

    role_display = {
        "held_condition": "held condition",
        "sweep_axis": "sweep axis",
        "measured_response": "measured response",
    }
    for column in figure["source_columns"]:
        lines.append(
            f"| `{column['name']}` | {role_display.get(column['role'], column['role'])} | `{column['unit']}` |"
        )

    lines.extend(
        [
            "",
            "Candidate figure panels:",
            "",
            "| Panel | X | Y | Source | Caution |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    caution_display = {
        "fixture-level plot hint only; no fit or quality claim": "plot hint only; no fit or quality claim",
        "derived relation is fixture-declared and not recomputed": "trace link only; not recomputed",
    }
    for plot in figure["candidate_plots"]:
        lines.append(
            f"| {plot['title']} | `{plot['x']}` | `{plot['y']}` | `{plot['source']}` | {caution_display.get(plot['caution'], plot['caution'])} |"
        )

    lines.extend(
        [
            "",
            "Missing for group-meeting interpretation:",
            "",
            "- calibration notes;",
            "- fit result;",
            "- uncertainty estimate.",
            "",
            "## Linked Context",
            "",
            "Present:",
            "",
            f"- source record for run `{selected['legacy_data_id']}`;",
            f"- copied parameter snapshot: `{parameter_path}`;",
            f"- companion artifact: `{companion_present}`;",
            f"- derived artifact: `{derived_path}`.",
            "",
            "No Silent Transform:",
            "",
            f"- source record for run `{selected['legacy_data_id']}` should not be silently compressed, converted,",
            "  filtered, or otherwise transformed during export:",
            f"  `{source_ref['source_file']}`.",
            "",
            "Missing:",
            "",
            f"- `{companion_missing}`.",
            "",
            "## Warnings",
            "",
            "- `local_only_path`: the original source path is redaction-sensitive and not",
            f"  portable. Use `{warnings['local_only_path']['public_safe_value']}` as the public-safe",
            "  display value.",
            "- `missing_companion`: a referenced calibration-notes companion is absent.",
            "- `figure_readiness_partial`: the handoff includes experiment label, measured",
            "  columns, context, and plot candidates, but calibration notes, fit results,",
            "  uncertainty, and scientific selection rationale are missing.",
            "",
            "## Boundary Notes",
            "",
            "- Selected source data should not be silently compressed, converted,",
            "  filtered, or otherwise transformed during export. This fixture does not",
            "  define a final checksum or package contract.",
            "- The handoff preserves where the selected data was exported from using a",
            "  public-safe source reference.",
            "- Source data, copied parameter context, companion artifact, and derived",
            "  artifact are represented as distinct handoff material.",
            "- Derived artifact relations are linked by fixture declaration; this fixture",
            "  does not recompute the analysis.",
            "- Selected means handed off for later work, not proven good, reproducible,",
            "  or reference-worthy.",
            "",
            "## Reviewer Questions",
            "",
            "A reviewer should be able to answer:",
            "",
            f"- selected run: `{selected['legacy_data_id']}`;",
            "- preserved source identity: session, encoded filename, numeric ID, and fixture",
            "  source file;",
            "- export trust: the output says where the selected data was exported from and",
            "  which source file should not be silently transformed during export;",
            "- figure readiness: the output names the experiment type, target, source",
            "  columns, candidate plot axes, relevant parameter context, and missing",
            "  scientific annotations;",
            f"- parameter context: `{parameter_path}`;",
            "- companion context: one present IQ summary and one missing calibration note;",
            f"- derived context: `{derived_path}`;",
            "- portability issue: local-only path is redacted;",
            "- trust boundary: no scientific validation, reanalysis, storage, sync, or",
            "  package-format decision is earned.",
            "",
        ]
    )
    return "\n".join(lines)

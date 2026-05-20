"""Generate expected outputs for preview-ready selected measurement export.

This module is a validation spike, not product code or a durable export schema.
It intentionally supports only the public-safe fixture under
``tests/fixtures/selected_run_handoff/preview_ready_measurement_export``.

Structured summary building is delegated to the implementation candidate. This
spike owns fixture loading, warning-expectation checks, CLI output, and Markdown
review support.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from implementation_candidates.selected_measurement_export import (
    build_selected_measurement_export_summary,
)

REFERENCE_SEMANTICS = {
    "status": "fixture_paths_are_package_relative",
    "contract_guard": (
        "This expected output is not a final package format, schema contract, "
        "storage layout, or path-addressed identity model."
    ),
    "path_fields": (
        "source_file, path, and plot candidate source fields are package-relative "
        "materialized fixture files for openability checks."
    ),
    "export_source": (
        "export_source preserves recoverable source provenance and is not "
        "necessarily the current read location."
    ),
    "external_reference_mode": (
        "External-reference-only workflows are a deferred transition mode with "
        "weaker durability guarantees."
    ),
    "managed_storage_identity": (
        "Future managed Scopecat data may use record IDs, artifact IDs, storage "
        "object references, or backend handles."
    ),
}

SUPPORTED_FIXTURE_ID = "preview-ready-measurement-export"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def generate_candidate_summary(fixture_root: Path) -> dict[str, Any]:
    source = load_json(fixture_root / "export-input.json")
    if source["fixture_id"] != SUPPORTED_FIXTURE_ID:
        raise ValueError(
            f"unsupported fixture_id {source['fixture_id']!r}; expected {SUPPORTED_FIXTURE_ID!r}"
        )
    return build_selected_measurement_export_summary(source)


def generate_summary(fixture_root: Path) -> dict[str, Any]:
    source = load_json(fixture_root / "export-input.json")
    if source["fixture_id"] != SUPPORTED_FIXTURE_ID:
        raise ValueError(
            f"unsupported fixture_id {source['fixture_id']!r}; expected {SUPPORTED_FIXTURE_ID!r}"
        )
    candidate_summary = generate_candidate_summary(fixture_root)
    summary = {
        "export_summary_id": f"{source['fixture_id']}.expected",
        "status": "expected_validation_output",
        "source_fixture": "export-input.json",
        "reference_semantics": REFERENCE_SEMANTICS,
        "candidate_summary": candidate_summary,
    }

    emitted_warning_codes = [warning["code"] for warning in candidate_summary["warnings"]]
    expected_warning_codes = source["warnings_expected"]
    unique_emitted_codes = list(dict.fromkeys(emitted_warning_codes))
    if unique_emitted_codes != expected_warning_codes:
        raise ValueError("generated warning codes do not match fixture warnings_expected")
    return summary


def _format_ids(ids: list[int]) -> str:
    return ", ".join(f"`{item}`" for item in ids)


def _measurement_by_id(summary: dict[str, Any], legacy_data_id: int) -> dict[str, Any]:
    for measurement in summary["measurements"]:
        if measurement["legacy_data_id"] == legacy_data_id:
            return measurement
    raise ValueError(f"missing measurement {legacy_data_id}")


def _linked_by_status(summary: dict[str, Any], include_status: str) -> list[dict[str, Any]]:
    return [item for item in summary["linked_context"] if item["include_status"] == include_status]


def _warning_lines(summary: dict[str, Any]) -> list[str]:
    return [f"- `{warning['code']}`: {warning['message']}" for warning in summary["warnings"]]


def _format_item_list(items: list[dict[str, Any]]) -> str:
    return "; ".join(f"{item['label']} (`{item['path']}`)" for item in items)


def _format_linked_ids(item: dict[str, Any]) -> str:
    return _format_ids(item["linked_legacy_data_ids"])


def _included_by_default_rows(summary: dict[str, Any]) -> list[str]:
    rows = [
        "| Measurement | Experiment | Included items |",
        "| --- | --- | --- |",
    ]
    for measurement in summary["measurements"]:
        rows.append(
            f"| `{measurement['legacy_data_id']}` | {measurement['experiment_label']} | "
            f"{_format_item_list(measurement['default_bundle'])} |"
        )
    return rows


def _linked_context_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- none"]
    return [
        (
            f"- {item['label']} (`{item['path']}`): `{item['kind']}`; "
            f"relation `{item['relation']}`; authority `{item['authority']}`; "
            f"linked measurements {_format_linked_ids(item)}."
        )
        for item in items
    ]


def _role_summary(preview: dict[str, Any]) -> str:
    roles = preview["declared_roles"]
    if not roles:
        return "none"
    return "; ".join(f"`{role['name']}` {role['role'].replace('_', ' ')}" for role in roles)


def _plot_candidate_summary(preview: dict[str, Any]) -> str:
    candidates = preview["plot_candidates"]
    if not candidates:
        return "none"
    return "; ".join(f"`{candidate['x']}` -> `{candidate['y']}`" for candidate in candidates)


def _preview_warning_summary(preview: dict[str, Any]) -> str:
    warnings = preview["warnings"]
    if not warnings:
        return "none"
    return "; ".join(warning["code"] for warning in warnings)


def _preview_readiness_rows(summary: dict[str, Any]) -> list[str]:
    rows = [
        "| Measurement | Status | Shape | Declared roles | Plot candidates | Warning |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for measurement in summary["measurements"]:
        preview = measurement["preview"]
        shape = preview["shape_kind"] if preview["shape_kind"] is not None else "none"
        rows.append(
            f"| `{measurement['legacy_data_id']}` | `{preview['status']}` | "
            f"`{shape}` | {_role_summary(preview)} | "
            f"{_plot_candidate_summary(preview)} | {_preview_warning_summary(preview)} |"
        )
    return rows


def _source_provenance_lines(summary: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for measurement in summary["measurements"]:
        lines.append(
            f"  - `{measurement['legacy_data_id']}`: `{measurement['export_source']}`; "
            f"data handling `{measurement['source_transform_policy']}`."
        )
    return lines


def _public_safe_source_line(summary: dict[str, Any]) -> str | None:
    for warning in summary["warnings"]:
        if warning["code"] == "local_only_path":
            return f"- public-safe source location: `{warning['public_safe_value']}`"
    return None


def generate_review(summary: dict[str, Any]) -> str:
    candidate_summary = summary["candidate_summary"]
    export_set = candidate_summary["selected_export_set"]
    included_by_user = _linked_by_status(candidate_summary, "included_by_user")
    visible_excluded = _linked_by_status(candidate_summary, "visible_excluded")
    missing = _linked_by_status(candidate_summary, "missing")
    public_safe_source = _public_safe_source_line(candidate_summary)

    lines = [
        "# Expected Preview-Ready Measurement Export Review",
        "",
        "## Fixture Wrapper",
        "",
        f"- expected output id: `{summary['export_summary_id']}`",
        f"- status: `{summary['status']}`",
        f"- source fixture: `{summary['source_fixture']}`",
        f"- reference semantics: `{summary['reference_semantics']['status']}`",
        f"- guard: {summary['reference_semantics']['contract_guard']}",
        "",
        "Fixture `path` and `source_file` values are package-relative materialized test",
        "files. They are not the final storage identity model.",
        "",
        "## Candidate Summary Review",
        "",
        "### Selected Export Set",
        "",
        f"- selection mode: `{export_set['selection_mode']}`",
        f"- selected measurements: {_format_ids(export_set['selected_legacy_data_ids'])}",
        f"- traversal policy: `{export_set['traversal_policy']}`",
        "",
        "Selecting these measurements exports their default source/metadata bundles.",
        "Linked files are reported with declared inclusion status and are not recursively",
        "traversed.",
        "",
        "### Included By Default",
        "",
        *_included_by_default_rows(candidate_summary),
        "",
        "### User-Included Optional Context",
        "",
        *_linked_context_lines(included_by_user),
        "",
        "### Visible But Excluded Optional Context",
        "",
        *_linked_context_lines(visible_excluded),
        "",
        "The excluded artifact is visible so a user can decide whether to include it in",
        "a later export. This fixture does not treat it as proof of analysis lineage.",
        "",
        "### Missing Context",
        "",
        *_linked_context_lines(missing),
        "",
        "### Preview Readiness",
        "",
        *_preview_readiness_rows(candidate_summary),
        "",
        "Preview readiness supports later export-side selection and import-side",
        "confirmation. It is not rendered plotting, fit validation, uncertainty,",
        "reproducibility, or scientific validation. Missing preview metadata degrades the",
        "preview surface but does not block export when source identity and primary data",
        "are present.",
        "",
        "The fixture intentionally does not infer preview roles from measurement `1002`",
        "CSV headers.",
        "",
        "### Source Recovery And Data Handling",
        "",
        *(
            ["- public-safe source location is unavailable."]
            if public_safe_source is None
            else [public_safe_source]
        ),
        "- local source path is redaction-sensitive and not portable.",
        "- selected source data should not be silently compressed, converted, filtered,",
        "  or replaced by a derived copy during export.",
        "- source provenance:",
        *_source_provenance_lines(candidate_summary),
        "",
        "### Warnings",
        "",
        *_warning_lines(candidate_summary),
        "",
        "## Boundary Notes",
        "",
        "- normal source data handling is represented as `source_transform_policy`, not",
        "  as a warning.",
        "- visible-but-excluded linked context is represented by `include_status`, not",
        "  as a warning.",
        "- non-recursive traversal is represented by `traversal_policy`, not as a",
        "  warning.",
        "- this review is not claiming analysis lineage, fit validity, scientific",
        "  validity, or reproducibility.",
        "",
        "## Reviewer Questions",
        "",
        "A reviewer should be able to answer:",
        "",
        "- which measurements were intentionally selected;",
        "- which primary data and metadata are included by default;",
        "- which optional linked file was included by user choice;",
        "- which optional linked file is visible but excluded;",
        "- which preview metadata is ready and which measurement has degraded preview;",
        "- which source files should not be silently transformed;",
        "- which context is missing;",
        "- that Scopecat is not claiming a downstream analysis DAG or scientific",
        "  validation.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture_root", type=Path)
    parser.add_argument(
        "--format",
        choices=["candidate-summary", "summary", "review"],
        default="summary",
    )
    args = parser.parse_args()

    if args.format == "candidate-summary":
        print(json.dumps(generate_candidate_summary(args.fixture_root), indent=2))
        return

    summary = generate_summary(args.fixture_root)
    if args.format == "summary":
        print(json.dumps(summary, indent=2))
    else:
        print(generate_review(summary), end="")


if __name__ == "__main__":
    main()

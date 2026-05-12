#!/usr/bin/env python3
"""Read-only JC-001 passive evidence-view prototype.

This prototype is intentionally fixture-sized. It reads a public-safe fixture
manifest, JSON artifacts, and code artifacts as text, then emits structured
JSON and Markdown evidence views. It does not import fixture code, execute
source files, mutate inputs, inspect hardware, or infer source-of-record truth.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROLE_MAP = {
    "anchor": "anchor",
    "selected-context candidate": "selected context",
    "selected context": "selected context",
    "setup evidence": "setup evidence",
    "generated sidecar": "generated sidecar",
    "run-bound copied snapshot": "copied snapshot",
    "copied snapshot": "copied snapshot",
    "variant and backup ambiguity": "variant",
    "variant": "variant",
    "code-shape evidence": "code reference",
    "code reference": "code reference",
    "readiness hint": "readiness hint",
}


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    path: str
    role: str
    status: str
    evidence_handling: str
    sharing_boundary: str


def artifact_id(path: str) -> str:
    return (
        path.replace(" - ", "-")
        .replace("/", "__")
        .replace(".", "_")
        .replace(" ", "_")
        .lower()
    )


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalize_role(role: str) -> str:
    return ROLE_MAP.get(role, "unknown")


def flatten_keys(value: Any, prefix: str = "") -> set[str]:
    if isinstance(value, dict):
        keys: set[str] = set()
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            keys.add(child_prefix)
            keys.update(flatten_keys(child, child_prefix))
        return keys
    if isinstance(value, list):
        return {prefix} if prefix else set()
    return {prefix} if prefix else set()


def relation(
    relation_id: str,
    relation_type: str,
    source: str,
    target: str,
    evidence_handling: str,
    confidence_narrative: str,
    flags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "relation_id": relation_id,
        "relation_type": relation_type,
        "source_artifact": source,
        "target_artifact": target,
        "evidence_handling": evidence_handling,
        "confidence_narrative": confidence_narrative,
        "flags": flags or [],
    }


def build_artifacts(manifest: dict[str, Any]) -> list[Artifact]:
    artifacts = []
    for item in manifest["artifacts"]:
        path = item["path"]
        artifacts.append(
            Artifact(
                artifact_id=artifact_id(path),
                path=path,
                role=normalize_role(item["role"]),
                status=item["status"],
                evidence_handling=item["evidence_handling"],
                sharing_boundary=item["sharing_boundary"],
            )
        )
    return artifacts


def collect_json_artifacts(fixture_dir: Path, artifacts: list[Artifact]) -> dict[str, Any]:
    payloads: dict[str, Any] = {}
    for artifact in artifacts:
        path = fixture_dir / artifact.path
        if path.suffix == ".json":
            payloads[artifact.path] = load_json(path)
    return payloads


def collect_code_text(fixture_dir: Path, artifacts: list[Artifact]) -> dict[str, str]:
    code_text: dict[str, str] = {}
    for artifact in artifacts:
        path = fixture_dir / artifact.path
        if artifact.role == "code reference":
            code_text[artifact.path] = read_text(path)
    return code_text


def find_first_by_role(artifacts: list[Artifact], role: str) -> Artifact | None:
    return next((artifact for artifact in artifacts if artifact.role == role), None)


def make_conflict(
    conflict_id: str,
    artifacts: list[str],
    conflict_type: str,
    affected_fact: str,
    implication: str,
    next_check: str,
) -> dict[str, Any]:
    return {
        "conflict_id": conflict_id,
        "artifacts": artifacts,
        "conflict_type": conflict_type,
        "affected_producer_fact": affected_fact,
        "user_visible_implication": implication,
        "next_check": next_check,
    }


def make_missing_fact(
    fact_id: str,
    fact_type: str,
    artifacts: list[str],
    user_impact: str,
    suggested_next_check: str,
) -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "fact_type": fact_type,
        "affected_artifacts": artifacts,
        "user_impact": user_impact,
        "suggested_next_check": suggested_next_check,
    }


def build_evidence_view(fixture_dir: Path) -> dict[str, Any]:
    fixture_dir = fixture_dir.resolve()
    manifest = load_json(fixture_dir / "fixture-manifest.json")
    artifacts = build_artifacts(manifest)
    by_path = {artifact.path: artifact for artifact in artifacts}
    json_payloads = collect_json_artifacts(fixture_dir, artifacts)
    code_text = collect_code_text(fixture_dir, artifacts)

    bundle_id = manifest["fixture_id"]
    relations: list[dict[str, Any]] = []

    anchors = [artifact for artifact in artifacts if artifact.role == "anchor"]
    selected_context = find_first_by_role(artifacts, "selected context")
    setup_context = find_first_by_role(artifacts, "setup evidence")
    generated_sidecars = [artifact for artifact in artifacts if artifact.role == "generated sidecar"]
    copied_snapshots = [artifact for artifact in artifacts if artifact.role == "copied snapshot"]
    variants = [artifact for artifact in artifacts if artifact.role == "variant"]
    code_refs = [artifact for artifact in artifacts if artifact.role == "code reference"]
    readiness_hints = [artifact for artifact in artifacts if artifact.role == "readiness hint"]

    next_relation = 1

    def add_relation(
        relation_type: str,
        source: str,
        target: str,
        evidence_handling: str,
        confidence_narrative: str,
        flags: list[str] | None = None,
    ) -> None:
        nonlocal next_relation
        relations.append(
            relation(
                f"rel-{next_relation:03d}",
                relation_type,
                source,
                target,
                evidence_handling,
                confidence_narrative,
                flags,
            )
        )
        next_relation += 1

    for anchor in anchors:
        flags = ["multiple-anchor-candidates"] if len(anchors) > 1 else []
        add_relation(
            "anchors",
            anchor.artifact_id,
            bundle_id,
            "observed",
            "Fixture manifest marks this artifact as a bundle anchor candidate.",
            flags,
        )

    if selected_context is not None:
        add_relation(
            "appears-selected-for",
            selected_context.artifact_id,
            bundle_id,
            "inferred",
            "Manifest role and static code text point to this artifact as selected-looking context.",
            ["non-authoritative"],
        )

    if setup_context is not None:
        add_relation(
            "appears-selected-for",
            setup_context.artifact_id,
            bundle_id,
            "inferred",
            "Setup evidence sits beside selected context but is not proven physical truth.",
            ["non-authoritative", "setup-evidence"],
        )

    for sidecar in generated_sidecars:
        payload = json_payloads.get(sidecar.path, {})
        source_path = payload.get("generated_from")
        target = by_path.get(source_path, selected_context)
        add_relation(
            "generated-from",
            sidecar.artifact_id,
            target.artifact_id if target else bundle_id,
            "observed" if source_path else "inferred",
            "Generated sidecar declares or implies selected context as its source.",
            ["freshness-unchecked"],
        )

    for snapshot in copied_snapshots:
        payload = json_payloads.get(snapshot.path, {})
        source_path = payload.get("copied_from")
        target = by_path.get(source_path, selected_context)
        add_relation(
            "copied-from",
            snapshot.artifact_id,
            target.artifact_id if target else bundle_id,
            "observed" if source_path else "inferred",
            "Copied snapshot declares or implies selected context as its source.",
            ["partial-snapshot"],
        )

    for code_ref in code_refs:
        add_relation(
            "references-code",
            code_ref.artifact_id,
            selected_context.artifact_id if selected_context else bundle_id,
            "observed",
            "Code artifact was read as text and contains static path or derivation clues.",
            ["not-executed"],
        )

    for variant in variants:
        add_relation(
            "has-variant",
            variant.artifact_id,
            bundle_id,
            "observed",
            "Variant manifest preserves branch ambiguity without importing full branch data.",
            ["manifest-only"],
        )
        add_relation(
            "has-backup",
            variant.artifact_id,
            bundle_id,
            "inferred",
            "Fixture preserves variant and backup ambiguity at manifest level.",
            ["manifest-only", "backup-ambiguous"],
        )

    conflicts: list[dict[str, Any]] = []

    def add_conflict(conflict_item: dict[str, Any]) -> None:
        conflicts.append(conflict_item)
        source, target = conflict_item["artifacts"][:2]
        add_relation(
            "conflicts-with",
            source,
            target,
            "inferred",
            conflict_item["user_visible_implication"],
            [conflict_item["conflict_type"]],
        )

    root_params = json_payloads.get("parameters.json", {})
    selected_params = json_payloads.get("setting/parameters.json", {})
    if root_params and selected_params and flatten_keys(root_params) != flatten_keys(selected_params):
        add_conflict(
            make_conflict(
                "conflict-001",
                [by_path["parameters.json"].artifact_id, by_path["setting/parameters.json"].artifact_id],
                "shape-drift",
                "active parameter source",
                "Root parameters and selected settings differ in coverage and shape; the prototype must not choose a winner.",
                "Ask the producer for selected settings path and selection reason.",
            )
        )

    root_registry = json_payloads.get("registry.json", {})
    selected_registry = json_payloads.get("setting/registry.json", {})
    if root_registry and selected_registry and flatten_keys(root_registry) != flatten_keys(selected_registry):
        add_conflict(
            make_conflict(
                "conflict-002",
                [by_path["registry.json"].artifact_id, by_path["setting/registry.json"].artifact_id],
                "setup-context-drift",
                "active setup registry",
                "Root registry and selected registry differ; this is setup-shaped evidence, not physical truth.",
                "Ask whether setup evidence is selected, copied, or session-injected.",
            )
        )

    for snapshot in copied_snapshots:
        snapshot_keys = flatten_keys(json_payloads.get(snapshot.path, {}))
        selected_keys = flatten_keys(selected_params)
        if selected_keys and not selected_keys <= snapshot_keys:
            add_conflict(
                make_conflict(
                    "conflict-003",
                    [snapshot.artifact_id, by_path["setting/parameters.json"].artifact_id],
                    "partial-snapshot",
                    "run-bound parameter snapshot coverage",
                    "Run snapshot preserves only part of selected context, so reopening cannot rely on it as full context.",
                    "Check producer rules for run-bound snapshot coverage.",
                )
            )

    missing_facts = [
        make_missing_fact(
            "missing-001",
            "preferred anchor",
            [anchor.artifact_id for anchor in anchors],
            "The evidence view can show anchor candidates but cannot decide the preferred entrypoint without producer intent.",
            "Record the bundle entry artifact when the bundle is produced.",
        ),
        make_missing_fact(
            "missing-002",
            "selected settings authority",
            [selected_context.artifact_id] if selected_context else [],
            "Selected-looking context is visible but not authoritative.",
            "Record settings path, selection reason, and producer timestamp.",
        ),
        make_missing_fact(
            "missing-003",
            "generated sidecar freshness",
            [sidecar.artifact_id for sidecar in generated_sidecars],
            "Derived files can be explained but not trusted as current without generation metadata.",
            "Record generation source, generation time, and invalidation rule.",
        ),
        make_missing_fact(
            "missing-004",
            "snapshot coverage",
            [snapshot.artifact_id for snapshot in copied_snapshots],
            "Copied snapshots need explicit coverage before they can stand in for selected context.",
            "Record copied snapshot source and coverage.",
        ),
        make_missing_fact(
            "missing-005",
            "code identity",
            [code_ref.artifact_id for code_ref in code_refs],
            "Code-shaped evidence explains likely flow, but it is not an immutable code reference.",
            "Record code origin or immutable reference when producer support is added.",
        ),
    ]

    for fact in missing_facts:
        add_relation(
            "missing-fact",
            fact["affected_artifacts"][0] if fact["affected_artifacts"] else bundle_id,
            bundle_id,
            "missing",
            fact["user_impact"],
            [fact["fact_type"]],
        )

    add_relation(
        "redacts",
        bundle_id,
        "public evidence view",
        "generated",
        "Public-safe output preserves artifact roles and relation existence while avoiding sensitive source details.",
    )

    inventory = [
        {
            "artifact_id": artifact.artifact_id,
            "label": artifact.path,
            "role": artifact.role,
            "status": artifact.status,
            "evidence_handling": artifact.evidence_handling,
            "sharing_boundary": artifact.sharing_boundary,
            "included_reason": "listed in fixture manifest",
        }
        for artifact in artifacts
    ]

    return {
        "bundle_summary": {
            "bundle_id": bundle_id,
            "source_boundary": "caller-provided fixture directory",
            "sharing_boundary": manifest["redaction_policy"]["source"],
            "purpose": manifest["purpose"],
            "execution_boundary": "read JSON and code text only; do not import or execute fixture code",
            "mutation_boundary": "input fixture files are not modified",
        },
        "artifact_role_inventory": inventory,
        "selected_context_explanation": {
            "selected_context_candidate": selected_context.artifact_id if selected_context else None,
            "setup_context_candidate": setup_context.artifact_id if setup_context else None,
            "selection_evidence": [
                "fixture manifest role",
                "static code text clues" if code_text else "no code text clue",
            ],
            "status": "selected-looking evidence only",
        },
        "generated_and_copied_relation_summary": {
            "generated_sidecars": [sidecar.artifact_id for sidecar in generated_sidecars],
            "copied_snapshots": [snapshot.artifact_id for snapshot in copied_snapshots],
        },
        "code_reference_summary": {
            "code_references": [code_ref.artifact_id for code_ref in code_refs],
            "observed_static_clues": {
                path: {
                    "mentions_setting": "setting" in text.lower(),
                    "mentions_snapshot": "snapshot" in text.lower(),
                    "mentions_sidecar": "sidecar" in text.lower() or "temp/" in text.lower(),
                }
                for path, text in code_text.items()
            },
            "execution_boundary": "not executed, imported, installed, or rewritten",
        },
        "readiness_hint_summary": {
            "readiness_hints": [hint.artifact_id for hint in readiness_hints],
            "status": "no static readiness hints observed"
            if not readiness_hints
            else "static readiness hints observed",
        },
        "variant_backup_unknown_summary": {
            "variant_artifacts": [variant.artifact_id for variant in variants],
            "backup_ambiguity_visible": bool(variants),
            "unknown_artifacts": [artifact.artifact_id for artifact in artifacts if artifact.role == "unknown"],
        },
        "relations": relations,
        "conflict_and_missing_fact_report": {
            "conflicts": conflicts,
            "missing_facts": missing_facts,
        },
        "sharing_boundary_summary": {
            "artifact_boundaries": [
                {
                    "artifact_id": artifact.artifact_id,
                    "sharing_boundary": artifact.sharing_boundary,
                    "redaction_behavior": "preserve role and relation existence; avoid sensitive source details",
                    "public_safe_replacement_label": artifact.role,
                }
                for artifact in artifacts
            ],
            "forbidden_content_categories": manifest["redaction_policy"]["forbidden_content"],
        },
        "static_shape_checks": {
            "role_counts": dict(sorted(Counter(artifact.role for artifact in artifacts).items())),
            "artifact_count": len(artifacts),
            "relation_types": sorted({item["relation_type"] for item in relations}),
            "conflict_count": len(conflicts),
            "missing_fact_count": len(missing_facts),
        },
        "next_checks": [
            "Record the preferred bundle anchor when a producer writes bundles.",
            "Record selected settings path, selection reason, and freshness marker.",
            "Record generated sidecar source and invalidation rule.",
            "Record snapshot source and coverage.",
            "Keep code references static until code identity ownership is accepted.",
        ],
    }


def render_markdown(view: dict[str, Any]) -> str:
    lines = [
        "# JC-001 Passive Evidence View",
        "",
        "## Bundle Summary",
        "",
        f"- Bundle ID: `{view['bundle_summary']['bundle_id']}`",
        f"- Source boundary: {view['bundle_summary']['source_boundary']}",
        f"- Sharing boundary: {view['bundle_summary']['sharing_boundary']}",
        f"- Execution boundary: {view['bundle_summary']['execution_boundary']}",
        f"- Mutation boundary: {view['bundle_summary']['mutation_boundary']}",
        "",
        "## Artifact-Role Inventory",
        "",
        "| Artifact | Role | Evidence handling | Sharing boundary |",
        "| --- | --- | --- | --- |",
    ]

    for artifact in view["artifact_role_inventory"]:
        lines.append(
            f"| `{artifact['label']}` | {artifact['role']} | "
            f"{artifact['evidence_handling']} | {artifact['sharing_boundary']} |"
        )

    lines.extend(
        [
            "",
            "## Selected-Context Explanation",
            "",
            f"- Selected context candidate: `{view['selected_context_explanation']['selected_context_candidate']}`",
            f"- Setup context candidate: `{view['selected_context_explanation']['setup_context_candidate']}`",
            f"- Status: {view['selected_context_explanation']['status']}",
            "",
            "## Generated And Copied Relation Summary",
            "",
            "- Generated sidecars: "
            + ", ".join(f"`{item}`" for item in view["generated_and_copied_relation_summary"]["generated_sidecars"]),
            "- Copied snapshots: "
            + ", ".join(f"`{item}`" for item in view["generated_and_copied_relation_summary"]["copied_snapshots"]),
            "",
            "## Code-Reference Summary",
            "",
            "- Code references: "
            + ", ".join(f"`{item}`" for item in view["code_reference_summary"]["code_references"]),
            f"- Execution boundary: {view['code_reference_summary']['execution_boundary']}",
            "- Readiness hints: "
            + (
                ", ".join(f"`{item}`" for item in view["readiness_hint_summary"]["readiness_hints"])
                or "none observed"
            ),
            "",
            "## Variant, Backup, And Unknown Artifact Summary",
            "",
            "- Variant artifacts: "
            + ", ".join(f"`{item}`" for item in view["variant_backup_unknown_summary"]["variant_artifacts"]),
            f"- Backup ambiguity visible: `{view['variant_backup_unknown_summary']['backup_ambiguity_visible']}`",
            "- Unknown artifacts: "
            + (
                ", ".join(f"`{item}`" for item in view["variant_backup_unknown_summary"]["unknown_artifacts"])
                or "none"
            ),
            "",
            "## Conflict And Missing-Fact Report",
            "",
            "| ID | Type | Implication | Next check |",
            "| --- | --- | --- | --- |",
        ]
    )

    for item in view["conflict_and_missing_fact_report"]["conflicts"]:
        lines.append(
            f"| `{item['conflict_id']}` | {item['conflict_type']} | "
            f"{item['user_visible_implication']} | {item['next_check']} |"
        )

    lines.extend(["", "| ID | Type | Impact | Suggested next check |", "| --- | --- | --- | --- |"])
    for item in view["conflict_and_missing_fact_report"]["missing_facts"]:
        lines.append(
            f"| `{item['fact_id']}` | {item['fact_type']} | "
            f"{item['user_impact']} | {item['suggested_next_check']} |"
        )

    lines.extend(
        [
            "",
            "## Sharing-Boundary Summary",
            "",
            "- Public-safe output preserves roles and relation existence.",
            "- Forbidden content categories: "
            + ", ".join(view["sharing_boundary_summary"]["forbidden_content_categories"])
            + ".",
            "",
            "## Next Checks",
            "",
        ]
    )

    lines.extend(f"- {item}" for item in view["next_checks"])
    return "\n".join(lines) + "\n"


def write_outputs(view: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "evidence-view.json"
    markdown_path = output_dir / "evidence-view.md"
    json_path.write_text(json.dumps(view, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(view), encoding="utf-8")
    return json_path, markdown_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture_dir", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    view = build_evidence_view(args.fixture_dir)
    json_path, markdown_path = write_outputs(view, args.out_dir)
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")


if __name__ == "__main__":
    main()

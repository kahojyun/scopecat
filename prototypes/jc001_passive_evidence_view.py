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
import sys
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


class EvidenceViewError(RuntimeError):
    """Prototype-scoped input or output error."""


def artifact_id(path: str) -> str:
    return (
        path.replace(" - ", "-")
        .replace("/", "__")
        .replace(".", "_")
        .replace(" ", "_")
        .lower()
    )


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise EvidenceViewError(f"missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EvidenceViewError(f"invalid JSON in {path}: {exc.msg}") from exc
    except OSError as exc:
        raise EvidenceViewError(f"cannot read JSON file {path}: {exc}") from exc


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise EvidenceViewError(f"missing text artifact: {path}") from exc
    except OSError as exc:
        raise EvidenceViewError(f"cannot read text artifact {path}: {exc}") from exc


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


def canonical_payload(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def summarize_code_clues(code_text: dict[str, str]) -> dict[str, dict[str, bool]]:
    return {
        path: {
            "mentions_setting": "setting" in text.lower(),
            "mentions_snapshot": "snapshot" in text.lower(),
            "mentions_sidecar": "sidecar" in text.lower() or "temp/" in text.lower(),
        }
        for path, text in code_text.items()
    }


def is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def resolve_fixture_path(fixture_dir: Path, artifact_path: str) -> Path:
    path = Path(artifact_path)
    if path.is_absolute() or ".." in path.parts or "\\" in artifact_path:
        raise EvidenceViewError(f"manifest artifact path is not fixture-local: {artifact_path}")

    candidate = fixture_dir / artifact_path
    if not candidate.is_file():
        raise EvidenceViewError(f"manifest artifact does not exist: {artifact_path}")

    resolved = candidate.resolve()
    if not is_relative_to(resolved, fixture_dir):
        raise EvidenceViewError(f"manifest artifact escapes fixture directory: {artifact_path}")
    return resolved


def resolve_manifest_path(fixture_dir: Path) -> Path:
    manifest_path = fixture_dir / "fixture-manifest.json"
    if not manifest_path.is_file():
        raise EvidenceViewError(f"missing JSON file: {manifest_path}")

    resolved = manifest_path.resolve()
    if not is_relative_to(resolved, fixture_dir):
        raise EvidenceViewError("fixture manifest escapes fixture directory")
    return resolved


def ensure_output_outside_fixture(fixture_dir: Path, output_dir: Path) -> None:
    resolved_output = output_dir.resolve(strict=False)
    if is_relative_to(resolved_output, fixture_dir):
        raise EvidenceViewError("output directory must be outside the input fixture directory")


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


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceViewError(f"{label} must be an object")
    return value


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvidenceViewError(f"{label} must be a non-empty string")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise EvidenceViewError(f"{label} must be a list")
    return value


def validate_manifest(manifest: Any, fixture_dir: Path) -> dict[str, Any]:
    manifest = require_mapping(manifest, "fixture-manifest.json")
    require_string(manifest.get("fixture_id"), "fixture_id")
    require_string(manifest.get("purpose"), "purpose")

    redaction_policy = require_mapping(manifest.get("redaction_policy"), "redaction_policy")
    require_string(redaction_policy.get("source"), "redaction_policy.source")
    forbidden_content = require_list(
        redaction_policy.get("forbidden_content"),
        "redaction_policy.forbidden_content",
    )
    for index, item in enumerate(forbidden_content):
        require_string(item, f"redaction_policy.forbidden_content[{index}]")

    artifacts = require_list(manifest.get("artifacts"), "artifacts")
    if not artifacts:
        raise EvidenceViewError("artifacts must not be empty")

    seen_paths: set[str] = set()
    seen_artifact_ids: dict[str, str] = {}
    required_fields = ("path", "role", "status", "evidence_handling", "sharing_boundary")
    for index, raw_artifact in enumerate(artifacts):
        artifact = require_mapping(raw_artifact, f"artifacts[{index}]")
        for field in required_fields:
            require_string(artifact.get(field), f"artifacts[{index}].{field}")

        artifact_path = artifact["path"]
        if artifact_path in seen_paths:
            raise EvidenceViewError(f"duplicate manifest artifact path: {artifact_path}")
        seen_paths.add(artifact_path)
        generated_id = artifact_id(artifact_path)
        if generated_id in seen_artifact_ids:
            first_path = seen_artifact_ids[generated_id]
            raise EvidenceViewError(
                "duplicate generated artifact ID: "
                f"{generated_id} from {first_path} and {artifact_path}"
            )
        seen_artifact_ids[generated_id] = artifact_path
        resolve_fixture_path(fixture_dir, artifact_path)

    return manifest


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
        path = resolve_fixture_path(fixture_dir, artifact.path)
        if path.suffix == ".json":
            payloads[artifact.path] = load_json(path)
    return payloads


def collect_code_text(fixture_dir: Path, artifacts: list[Artifact]) -> dict[str, str]:
    code_text: dict[str, str] = {}
    for artifact in artifacts:
        path = resolve_fixture_path(fixture_dir, artifact.path)
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


def display_ids(items: list[str]) -> str:
    return ", ".join(f"`{item}`" for item in items) or "none observed"


def declared_source_relation_target(
    *,
    source_path: Any,
    by_path: dict[str, Artifact],
    fallback: Artifact | None,
    bundle_id: str,
    relation_kind: str,
) -> tuple[str, str, str, list[str]]:
    if isinstance(source_path, str) and source_path:
        target = by_path.get(source_path)
        if target is not None:
            return (
                target.artifact_id,
                "observed",
                f"{relation_kind} declares a manifest-listed source artifact.",
                [],
            )
        return (
            bundle_id,
            "missing",
            f"{relation_kind} declares a source path that is not listed in the fixture manifest.",
            ["declared-source-unlisted"],
        )

    if fallback is not None:
        return (
            fallback.artifact_id,
            "inferred",
            f"{relation_kind} lacks a declared source; selected context is only an inferred fallback.",
            ["source-inferred"],
        )

    return (
        bundle_id,
        "missing",
        f"{relation_kind} has no declared source and no selected context fallback.",
        ["source-missing"],
    )


def build_evidence_view(fixture_dir: Path) -> dict[str, Any]:
    fixture_dir = fixture_dir.resolve()
    if not fixture_dir.is_dir():
        raise EvidenceViewError(f"fixture directory does not exist: {fixture_dir}")

    manifest = validate_manifest(load_json(resolve_manifest_path(fixture_dir)), fixture_dir)
    artifacts = build_artifacts(manifest)
    by_path = {artifact.path: artifact for artifact in artifacts}
    json_payloads = collect_json_artifacts(fixture_dir, artifacts)
    code_text = collect_code_text(fixture_dir, artifacts)
    code_clues = summarize_code_clues(code_text)
    has_selected_context_code_clue = any(
        clues["mentions_setting"] for clues in code_clues.values()
    )

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
            "Manifest role and static code text point to this artifact as selected-looking context."
            if has_selected_context_code_clue
            else "Manifest role marks this artifact as selected-looking context; no supporting code clue was observed.",
            ["non-authoritative"]
            if has_selected_context_code_clue
            else ["non-authoritative", "manifest-role-only"],
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
        target_id, evidence_handling, source_narrative, source_flags = declared_source_relation_target(
            source_path=source_path,
            by_path=by_path,
            fallback=selected_context,
            bundle_id=bundle_id,
            relation_kind="Generated sidecar",
        )
        add_relation(
            "generated-from",
            sidecar.artifact_id,
            target_id,
            evidence_handling,
            source_narrative,
            ["freshness-unchecked", *source_flags],
        )

    for snapshot in copied_snapshots:
        payload = json_payloads.get(snapshot.path, {})
        source_path = payload.get("copied_from")
        target_id, evidence_handling, source_narrative, source_flags = declared_source_relation_target(
            source_path=source_path,
            by_path=by_path,
            fallback=selected_context,
            bundle_id=bundle_id,
            relation_kind="Copied snapshot",
        )
        add_relation(
            "copied-from",
            snapshot.artifact_id,
            target_id,
            evidence_handling,
            source_narrative,
            ["partial-snapshot", *source_flags],
        )

    for code_ref in code_refs:
        clues = code_clues.get(code_ref.path, {})
        has_clue = any(clues.values())
        add_relation(
            "references-code",
            code_ref.artifact_id,
            selected_context.artifact_id if selected_context else bundle_id,
            "observed",
            "Code artifact was read as text and contains static path or derivation clues."
            if has_clue
            else "Code artifact was read as text; no selected-context clue was observed.",
            ["not-executed"] if has_clue else ["not-executed", "no-static-context-clue"],
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
    selected_params_path = selected_context.path if selected_context else "setting/parameters.json"
    selected_params = json_payloads.get(selected_params_path, {})
    root_params_present = "parameters.json" in json_payloads
    selected_params_present = selected_context is not None and selected_params_path in json_payloads
    if (
        root_params_present
        and selected_params_present
        and flatten_keys(root_params) != flatten_keys(selected_params)
    ):
        add_conflict(
            make_conflict(
                "conflict-001",
                [by_path["parameters.json"].artifact_id, selected_context.artifact_id],
                "shape-drift",
                "active parameter source",
                "Root parameters and selected settings differ in coverage and shape; the prototype must not choose a winner.",
                "Ask the producer for selected settings path and selection reason.",
            )
        )
    elif (
        root_params_present
        and selected_params_present
        and canonical_payload(root_params) != canonical_payload(selected_params)
    ):
        add_conflict(
            make_conflict(
                "conflict-001",
                [by_path["parameters.json"].artifact_id, selected_context.artifact_id],
                "value-drift",
                "active parameter source",
                "Root parameters and selected settings share a shape but differ in values; the prototype must not choose a winner.",
                "Ask the producer for selected settings path, selection reason, and freshness marker.",
            )
        )

    root_registry = json_payloads.get("registry.json", {})
    selected_registry = json_payloads.get("setting/registry.json", {})
    root_registry_present = "registry.json" in json_payloads
    selected_registry_present = "setting/registry.json" in json_payloads
    if (
        root_registry_present
        and selected_registry_present
        and flatten_keys(root_registry) != flatten_keys(selected_registry)
    ):
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
    elif (
        root_registry_present
        and selected_registry_present
        and canonical_payload(root_registry) != canonical_payload(selected_registry)
    ):
        add_conflict(
            make_conflict(
                "conflict-002",
                [by_path["registry.json"].artifact_id, by_path["setting/registry.json"].artifact_id],
                "setup-value-drift",
                "active setup registry",
                "Root registry and selected registry share a shape but differ in values; this is setup-shaped evidence, not physical truth.",
                "Ask whether setup evidence is selected, copied, session-injected, or stale.",
            )
        )

    for snapshot in copied_snapshots:
        snapshot_keys = flatten_keys(json_payloads.get(snapshot.path, {}))
        selected_keys = flatten_keys(selected_params)
        if selected_keys and not selected_keys <= snapshot_keys:
            add_conflict(
                make_conflict(
                    "conflict-003",
                    [snapshot.artifact_id, selected_context.artifact_id],
                    "partial-snapshot",
                    "run-bound parameter snapshot coverage",
                    "Run snapshot preserves only part of selected context, so reopening cannot rely on it as full context.",
                    "Check producer rules for run-bound snapshot coverage.",
                )
            )

    missing_facts = []
    next_missing_fact = 1

    def add_missing_fact(
        fact_type: str,
        affected_artifacts: list[str],
        user_impact: str,
        suggested_next_check: str,
    ) -> None:
        nonlocal next_missing_fact
        missing_facts.append(
            make_missing_fact(
                f"missing-{next_missing_fact:03d}",
                fact_type,
                affected_artifacts,
                user_impact,
                suggested_next_check,
            )
        )
        next_missing_fact += 1

    if len(anchors) != 1:
        add_missing_fact(
            "preferred anchor",
            [anchor.artifact_id for anchor in anchors],
            "The evidence view can show anchor candidates but cannot decide the preferred entrypoint without producer intent.",
            "Record the bundle entry artifact when the bundle is produced.",
        )

    if selected_context is not None:
        add_missing_fact(
            "selected settings provenance",
            [selected_context.artifact_id],
            "Selected-looking context is visible but not authoritative.",
            "Record settings path, selection reason, and producer timestamp.",
        )

    if generated_sidecars:
        add_missing_fact(
            "generated sidecar freshness",
            [sidecar.artifact_id for sidecar in generated_sidecars],
            "Derived files can be explained but not trusted as current without generation metadata.",
            "Record generation source, generation time, and invalidation rule.",
        )

    if copied_snapshots:
        add_missing_fact(
            "snapshot coverage",
            [snapshot.artifact_id for snapshot in copied_snapshots],
            "Copied snapshots need explicit coverage before they can stand in for selected context.",
            "Record copied snapshot source and coverage.",
        )

    if code_refs:
        add_missing_fact(
            "code identity",
            [code_ref.artifact_id for code_ref in code_refs],
            "Code-shaped evidence explains likely flow, but it is not an immutable code reference.",
            "Record code origin or immutable reference when producer support is added.",
        )

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
                "static code text clues"
                if has_selected_context_code_clue
                else "no selected-context code clue",
            ],
            "status": "selected-looking evidence only",
        },
        "generated_and_copied_relation_summary": {
            "generated_sidecars": [sidecar.artifact_id for sidecar in generated_sidecars],
            "copied_snapshots": [snapshot.artifact_id for snapshot in copied_snapshots],
        },
        "code_reference_summary": {
            "code_references": [code_ref.artifact_id for code_ref in code_refs],
            "observed_static_clues": code_clues,
            "execution_boundary": "not executed, imported, installed, or rewritten",
        },
        "readiness_hint_summary": {
            "readiness_hints": [hint.artifact_id for hint in readiness_hints],
            "readiness_hint_details": [
                {
                    "readiness_hint_id": hint.artifact_id,
                    "source_artifact": hint.artifact_id,
                    "category": "dependency/environment",
                    "evidence_handling": hint.evidence_handling,
                    "suggested_next_check": "Review dependency or environment evidence without executing fixture code.",
                }
                for hint in readiness_hints
            ],
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
        "next_checks": build_next_checks(
            anchors=anchors,
            selected_context=selected_context,
            generated_sidecars=generated_sidecars,
            copied_snapshots=copied_snapshots,
            code_refs=code_refs,
            readiness_hints=readiness_hints,
        ),
    }


def build_next_checks(
    *,
    anchors: list[Artifact],
    selected_context: Artifact | None,
    generated_sidecars: list[Artifact],
    copied_snapshots: list[Artifact],
    code_refs: list[Artifact],
    readiness_hints: list[Artifact],
) -> list[str]:
    next_checks: list[str] = []
    if len(anchors) != 1:
        next_checks.append("Record the preferred bundle anchor when a producer writes bundles.")
    if selected_context is not None:
        next_checks.append("Record selected settings path, selection reason, and freshness marker.")
    if generated_sidecars:
        next_checks.append("Record generated sidecar source and invalidation rule.")
    if copied_snapshots:
        next_checks.append("Record snapshot source and coverage.")
    if code_refs:
        next_checks.append("Keep code references static until code identity ownership is accepted.")
    if readiness_hints:
        next_checks.append("Keep readiness hints static until managed execution boundaries are accepted.")
    return next_checks


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
            "- Generated sidecars: " + display_ids(view["generated_and_copied_relation_summary"]["generated_sidecars"]),
            "- Copied snapshots: " + display_ids(view["generated_and_copied_relation_summary"]["copied_snapshots"]),
            "",
            "## Code-Reference Summary",
            "",
            "- Code references: " + display_ids(view["code_reference_summary"]["code_references"]),
            f"- Execution boundary: {view['code_reference_summary']['execution_boundary']}",
            "",
            "## Static Readiness Hint Summary",
            "",
            "- Readiness hints: " + display_ids(view["readiness_hint_summary"]["readiness_hints"]),
            "",
            "## Variant, Backup, And Unknown Artifact Summary",
            "",
            "- Variant artifacts: " + display_ids(view["variant_backup_unknown_summary"]["variant_artifacts"]),
            f"- Backup ambiguity visible: `{view['variant_backup_unknown_summary']['backup_ambiguity_visible']}`",
            "- Unknown artifacts: " + display_ids(view["variant_backup_unknown_summary"]["unknown_artifacts"]),
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
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "evidence-view.json"
        markdown_path = output_dir / "evidence-view.md"
        json_path.write_text(json.dumps(view, indent=2) + "\n", encoding="utf-8")
        markdown_path.write_text(render_markdown(view), encoding="utf-8")
        return json_path, markdown_path
    except OSError as exc:
        raise EvidenceViewError(f"failed to write evidence view to {output_dir}: {exc}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture_dir", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    try:
        fixture_dir = args.fixture_dir.resolve()
        ensure_output_outside_fixture(fixture_dir, args.out_dir)
        view = build_evidence_view(fixture_dir)
        json_path, markdown_path = write_outputs(view, args.out_dir)
    except EvidenceViewError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")


if __name__ == "__main__":
    main()

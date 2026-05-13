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
import posixpath
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROLE_MAP = {
    "anchor": "anchor",
    "selected-context candidate": "selected context",
    "selected context": "selected context",
    "fixture-authored": "fixture-authored",
    "setup evidence": "setup evidence",
    "generated sidecar": "generated sidecar",
    "run-bound copied snapshot": "copied snapshot",
    "copied snapshot": "copied snapshot",
    "variant": "variant",
    "code-shape evidence": "code reference",
    "code reference": "code reference",
    "readiness hint": "readiness hint",
}

ALLOWED_EVIDENCE_HANDLING = {
    "observed",
    "inferred",
    "generated",
    "copied",
    "user-declared",
    "unchecked",
    "unsafe-to-inspect",
    "missing",
}

ALLOWED_SHARING_BOUNDARIES = {
    "public-safe",
    "redaction-sensitive",
}

SETUP_REGISTRY_FALLBACK_ROLES = {
    "selected context",
    "setup evidence",
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


def raw_artifact_id(path: str) -> str:
    return (
        path.replace(" - ", "-")
        .replace("/", "__")
        .replace(".", "_")
        .replace(" ", "_")
        .lower()
    )


PUBLIC_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
PUBLIC_ID_HANDLE_PATTERN = re.compile(r"^[a-z][a-z0-9]{0,7}$")
HASH_LIKE_HANDLE_PATTERN = re.compile(r"[a-f0-9]{6,8}$")
MIN_SOURCE_DERIVED_TEXT_LENGTH = 4


def source_token_sequence(value: str) -> list[str]:
    raw_id = raw_artifact_id(value)
    return [
        token
        for token in re.split(r"[^a-z0-9]+", raw_id)
        if token and token not in {"json", "txt", "py", "md"}
    ]


def source_tokens(value: str) -> set[str]:
    return set(source_token_sequence(value))


def compact_public_text(value: str) -> str:
    return "".join(token for token in re.split(r"[^a-z0-9]+", value) if token)


def compact_source_texts(source_values: list[str]) -> list[str]:
    return ["".join(source_token_sequence(source_value)) for source_value in source_values]


def compact_source_match(compact_source: str, compact_candidate: str) -> bool:
    return (
        len(compact_source) >= MIN_SOURCE_DERIVED_TEXT_LENGTH
        and compact_source in compact_candidate
    )


def validate_fixture_authored_handle(handle: str, source_values: list[str], label: str) -> None:
    if not PUBLIC_ID_HANDLE_PATTERN.fullmatch(handle):
        raise EvidenceViewError(f"{label} must use a short fixture-authored handle")
    if HASH_LIKE_HANDLE_PATTERN.fullmatch(handle):
        raise EvidenceViewError(f"{label} must not look hash-derived")
    tokens: set[str] = set()
    raw_ids: set[str] = set()
    for source_value in source_values:
        raw_ids.add(raw_artifact_id(source_value))
        tokens.update(source_tokens(source_value))
    if not tokens and not raw_ids:
        return
    compact_sources = compact_source_texts(source_values)
    compact_handle = compact_public_text(handle)
    if (
        handle in raw_ids
        or handle in tokens
        or any(token in compact_handle for token in tokens if len(token) >= 4)
        or any(
            len(handle) >= 3 and (token.startswith(handle) or handle in token)
            for token in tokens
            if len(token) >= 4
        )
        or any(compact_source_match(compact_source, compact_handle) for compact_source in compact_sources)
    ):
        raise EvidenceViewError(f"{label} must not include source-derived text")


def contains_source_derived_text(candidate: str, source_values: list[str]) -> bool:
    candidate_tokens = {token for token in re.split(r"[^a-z0-9]+", candidate) if token}
    compact_candidate = compact_public_text(candidate)
    tokens: set[str] = set()
    raw_ids: set[str] = set()
    for source_value in source_values:
        raw_ids.add(raw_artifact_id(source_value))
        tokens.update(source_tokens(source_value))
    compact_sources = compact_source_texts(source_values)
    return (
        candidate in raw_ids
        or bool(candidate_tokens & tokens)
        or any(token in compact_candidate for token in tokens if len(token) >= 4)
        or any(
            len(candidate) >= 3 and (token.startswith(candidate) or candidate in token)
            for token in tokens
            if len(token) >= 4
        )
        or any(
            compact_source_match(compact_source, compact_candidate)
            for compact_source in compact_sources
        )
    )


def manifest_source_texts(manifest: dict[str, Any]) -> list[str]:
    texts = [
        manifest["fixture_id"],
        manifest["purpose"],
        manifest["redaction_policy"]["source"],
    ]
    texts.extend(manifest["redaction_policy"]["forbidden_content"])
    for artifact in manifest["artifacts"]:
        texts.extend([artifact["path"], artifact["status"]])
    return texts


def public_artifact_id(
    path: str,
    role: str,
    sharing_boundary: str,
    source_values: list[str],
    public_id: Any = None,
) -> str:
    if not isinstance(public_id, str) or not public_id.strip():
        raise EvidenceViewError("artifact requires public_id")
    replacement_id = public_id.strip()
    if not PUBLIC_ID_PATTERN.fullmatch(replacement_id):
        raise EvidenceViewError("public_id must be a public-safe slug")
    if sharing_boundary == "public-safe":
        if replacement_id.startswith("redacted-"):
            raise EvidenceViewError("public-safe artifact public_id must not be redacted")
        if contains_source_derived_text(replacement_id, source_values):
            raise EvidenceViewError("public_id must not include source-derived text")
        return replacement_id
    role_prefix = f"redacted-{role.replace(' ', '-')}-"
    if not replacement_id.startswith(role_prefix):
        raise EvidenceViewError("public_id must use the redacted role prefix")
    public_handle = replacement_id.removeprefix(role_prefix)
    validate_fixture_authored_handle(public_handle, source_values, "public_id")
    return replacement_id


def public_artifact_status(status: str, role: str, sharing_boundary: str) -> str:
    if sharing_boundary == "public-safe":
        return "public-safe"
    return "redacted"


def public_bundle_purpose(purpose: str, sharing_boundary: str) -> str:
    if sharing_boundary == "public-safe":
        return "public-safe manifest purpose retained in fixture"
    return "redacted non-public bundle purpose"


def public_bundle_id(
    fixture_id: str,
    sharing_boundary: str,
    source_values: list[str],
    public_id: Any = None,
) -> str:
    if not isinstance(public_id, str) or not public_id.strip():
        raise EvidenceViewError("fixture requires public_bundle_id")
    replacement_id = public_id.strip()
    if not PUBLIC_ID_PATTERN.fullmatch(replacement_id):
        raise EvidenceViewError("public_bundle_id must be a public-safe slug")
    if sharing_boundary == "public-safe":
        if replacement_id.startswith("redacted-"):
            raise EvidenceViewError("public-safe public_bundle_id must not be redacted")
        if contains_source_derived_text(replacement_id, source_values):
            raise EvidenceViewError("public_bundle_id must not include source-derived text")
        return replacement_id
    bundle_prefix = "redacted-work-bundle-"
    if not replacement_id.startswith(bundle_prefix):
        raise EvidenceViewError("public_bundle_id must use the redacted work-bundle prefix")
    public_handle = replacement_id.removeprefix(bundle_prefix)
    validate_fixture_authored_handle(public_handle, source_values, "public_bundle_id")
    return replacement_id


def public_redaction_policy_source(source: str, sharing_boundary: str) -> str:
    if sharing_boundary == "public-safe":
        return "public-safe redaction policy source retained in fixture"
    return "redacted non-public redaction policy source"


def public_forbidden_content_categories(categories: list[str], sharing_boundary: str) -> list[str]:
    if sharing_boundary == "public-safe":
        if not categories:
            return []
        return ["public-safe forbidden content categories retained in fixture"]
    if not categories:
        return []
    return ["redacted non-public forbidden content categories"]


def validate_public_identity_space(artifacts: list[Artifact], bundle_id: str) -> None:
    for artifact in artifacts:
        if artifact.artifact_id == bundle_id:
            raise EvidenceViewError(
                f"artifact ID collides with public bundle ID: {artifact.artifact_id}"
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
        if not prefix:
            return set()
        keys = {f"{prefix}[]"}
        for item in value:
            keys.update(flatten_keys(item, f"{prefix}[]"))
        return keys
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


def code_mentions_artifact_path(code_text: dict[str, str], artifact_path: str) -> bool:
    path_text = artifact_path.lower()
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_./\\-])(?:\./)?{re.escape(path_text)}(?![A-Za-z0-9_./\\-])"
    )
    for text in code_text.values():
        lowered = text.lower()
        if pattern.search(lowered):
            return True
    return False


def bundle_sharing_boundary(artifacts: list[Artifact]) -> str:
    rank = {
        "public-safe": 0,
        "redaction-sensitive": 1,
    }
    return max((artifact.sharing_boundary for artifact in artifacts), key=rank.__getitem__)


def is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def normalize_fixture_artifact_path(artifact_path: str) -> str:
    path = Path(artifact_path)
    if path.is_absolute() or ".." in path.parts or "\\" in artifact_path:
        raise EvidenceViewError(f"manifest artifact path is not fixture-local: {artifact_path}")
    return posixpath.normpath(artifact_path)


def resolve_fixture_path(fixture_dir: Path, artifact_path: str) -> Path:
    normalized_path = normalize_fixture_artifact_path(artifact_path)

    candidate = fixture_dir / normalized_path
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

        artifact_path = normalize_fixture_artifact_path(artifact["path"])
        artifact["path"] = artifact_path
        evidence_handling = artifact["evidence_handling"]
        sharing_boundary = artifact["sharing_boundary"]
        if evidence_handling not in ALLOWED_EVIDENCE_HANDLING:
            raise EvidenceViewError(
                f"artifacts[{index}].evidence_handling must be controlled vocabulary"
            )
        if sharing_boundary not in ALLOWED_SHARING_BOUNDARIES:
            raise EvidenceViewError(
                f"artifacts[{index}].sharing_boundary must be controlled vocabulary"
            )
        public_id = require_string(
            artifact.get("public_id"),
            f"artifacts[{index}].public_id",
        ).strip()
        if not PUBLIC_ID_PATTERN.fullmatch(public_id):
            raise EvidenceViewError(
                f"artifacts[{index}].public_id must be a public-safe slug"
            )
        if artifact_path in seen_paths:
            raise EvidenceViewError(f"duplicate manifest artifact path: {artifact_path}")
        seen_paths.add(artifact_path)
        generated_id = raw_artifact_id(artifact_path)
        if generated_id in seen_artifact_ids:
            first_path = seen_artifact_ids[generated_id]
            raise EvidenceViewError(
                "duplicate generated artifact ID: "
                f"{generated_id} from {first_path} and {artifact_path}"
            )
        seen_artifact_ids[generated_id] = artifact_path
        resolve_fixture_path(fixture_dir, artifact_path)

    return manifest


def build_artifacts(manifest: dict[str, Any], source_values: list[str]) -> list[Artifact]:
    artifacts = []
    seen_public_ids: dict[str, str] = {}
    for item in manifest["artifacts"]:
        path = item["path"]
        role = normalize_role(item["role"])
        sharing_boundary = item["sharing_boundary"]
        emitted_id = public_artifact_id(
            path,
            role,
            sharing_boundary,
            source_values,
            item.get("public_id"),
        )
        if emitted_id in seen_public_ids:
            first_path = seen_public_ids[emitted_id]
            raise EvidenceViewError(
                "duplicate emitted artifact ID: "
                f"{emitted_id} from {first_path} and {path}"
            )
        seen_public_ids[emitted_id] = path
        artifacts.append(
            Artifact(
                artifact_id=emitted_id,
                path=path,
                role=role,
                status=item["status"],
                evidence_handling=item["evidence_handling"],
                sharing_boundary=sharing_boundary,
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


def display_value(item: str | None) -> str:
    return f"`{item}`" if item else "none observed"


def display_flags(flags: list[str]) -> str:
    return ", ".join(f"`{flag}`" for flag in flags) or "none"


def positive_backup_label(value: Any) -> bool:
    normalized = str(value).strip().lower().replace("_", "-").replace(" ", "-")
    if normalized.startswith("no-backup") or normalized.startswith("non-backup"):
        return False
    return normalized in {"backup", "backup-ambiguity", "backup-branch"} or normalized.startswith(
        "backup-"
    )


def variant_has_backup_evidence(variant: Artifact, json_payloads: dict[str, Any]) -> bool:
    payload = json_payloads.get(variant.path)
    if not isinstance(payload, dict):
        return False
    entries = payload.get("entries", [])
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            role = str(entry.get("role", "")).lower()
            name = str(entry.get("name", "")).lower()
            if positive_backup_label(role) or positive_backup_label(name):
                return True
    role = str(payload.get("role", "")).lower()
    status = str(payload.get("status", "")).lower()
    return positive_backup_label(role) or positive_backup_label(status)


def normalize_declared_source_path(source_path: str) -> str:
    normalized = source_path.strip()
    try:
        return normalize_fixture_artifact_path(normalized)
    except EvidenceViewError:
        return normalized


def declared_source_relation_targets(
    *,
    source_path: Any,
    by_path: dict[str, Artifact],
    fallbacks: list[Artifact],
    bundle_id: str,
    relation_kind: str,
) -> list[tuple[str, str, str, list[str]]]:
    if isinstance(source_path, str) and source_path:
        normalized_source_path = normalize_declared_source_path(source_path)
        target = by_path.get(normalized_source_path)
        if target is not None:
            return [
                (
                    target.artifact_id,
                    "observed",
                    f"{relation_kind} declares a manifest-listed source artifact.",
                    [],
                )
            ]
        return [
            (
                bundle_id,
                "missing",
                f"{relation_kind} declares a source path that is not listed in the fixture manifest.",
                ["declared-source-unlisted"],
            )
        ]

    if len(fallbacks) == 1:
        return [
            (
                fallbacks[0].artifact_id,
                "inferred",
                f"{relation_kind} lacks a declared source; selected context is only an inferred fallback.",
                ["source-inferred"],
            )
        ]

    if len(fallbacks) > 1:
        return [
            (
                fallback.artifact_id,
                "inferred",
                f"{relation_kind} lacks a declared source; multiple selected-looking contexts remain possible sources.",
                ["source-inferred", "multiple-selected-context-candidates"],
            )
            for fallback in fallbacks
        ]

    return [
        (
            bundle_id,
            "missing",
            f"{relation_kind} has no declared source and no selected context fallback.",
            ["source-missing"],
        )
    ]


def build_evidence_view(fixture_dir: Path) -> dict[str, Any]:
    fixture_dir = fixture_dir.resolve()
    if not fixture_dir.is_dir():
        raise EvidenceViewError(f"fixture directory does not exist: {fixture_dir}")

    manifest = validate_manifest(load_json(resolve_manifest_path(fixture_dir)), fixture_dir)
    source_values = manifest_source_texts(manifest)
    artifacts = build_artifacts(manifest, source_values)
    bundle_boundary = bundle_sharing_boundary(artifacts)
    by_path = {artifact.path: artifact for artifact in artifacts}
    json_payloads = collect_json_artifacts(fixture_dir, artifacts)
    code_text = collect_code_text(fixture_dir, artifacts)
    source_values.extend(json.dumps(payload, sort_keys=True) for payload in json_payloads.values())
    source_values.extend(code_text.values())
    artifacts = build_artifacts(manifest, source_values)
    by_path = {artifact.path: artifact for artifact in artifacts}
    code_clues = summarize_code_clues(code_text)
    bundle_id = public_bundle_id(
        manifest["fixture_id"],
        bundle_boundary,
        source_values,
        manifest.get("public_bundle_id"),
    )
    validate_public_identity_space(artifacts, bundle_id)
    relations: list[dict[str, Any]] = []

    anchors = [artifact for artifact in artifacts if artifact.role == "anchor"]
    selected_contexts = [artifact for artifact in artifacts if artifact.role == "selected context"]
    selected_context = selected_contexts[0] if len(selected_contexts) == 1 else None
    setup_contexts = [artifact for artifact in artifacts if artifact.role == "setup evidence"]
    setup_context = setup_contexts[0] if len(setup_contexts) == 1 else None
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

    selected_context_code_clues = {
        artifact.artifact_id: code_mentions_artifact_path(code_text, artifact.path)
        for artifact in selected_contexts
    }
    has_selected_context_code_clue = any(selected_context_code_clues.values())

    for selected in selected_contexts:
        has_clue = selected_context_code_clues[selected.artifact_id]
        add_relation(
            "appears-selected-for",
            selected.artifact_id,
            bundle_id,
            "inferred",
            "Manifest role and static code text point to this artifact as selected-looking context."
            if has_clue
            else "Manifest role marks this artifact as selected-looking context; no supporting code clue was observed.",
            ["non-authoritative"]
            if has_clue
            else ["non-authoritative", "manifest-role-only"],
        )

    for setup_context_item in setup_contexts:
        add_relation(
            "appears-selected-for",
            setup_context_item.artifact_id,
            bundle_id,
            "inferred",
            "Setup evidence sits beside selected context but is not proven physical truth.",
            ["non-authoritative", "setup-evidence"],
        )

    for sidecar in generated_sidecars:
        payload = json_payloads.get(sidecar.path, {})
        source_path = payload.get("generated_from")
        source_targets = declared_source_relation_targets(
            source_path=source_path,
            by_path=by_path,
            fallbacks=selected_contexts,
            bundle_id=bundle_id,
            relation_kind="Generated sidecar",
        )
        for target_id, evidence_handling, source_narrative, source_flags in source_targets:
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
        source_targets = declared_source_relation_targets(
            source_path=source_path,
            by_path=by_path,
            fallbacks=selected_contexts,
            bundle_id=bundle_id,
            relation_kind="Copied snapshot",
        )
        for target_id, evidence_handling, source_narrative, source_flags in source_targets:
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
        matched_contexts = [
            selected
            for selected in selected_contexts
            if code_mentions_artifact_path({code_ref.path: code_text.get(code_ref.path, "")}, selected.path)
        ]
        target_contexts = matched_contexts
        targets = target_contexts or [None]
        for target_context in targets:
            target = target_context.artifact_id if target_context is not None else bundle_id
            flags = ["not-executed"]
            if not has_clue:
                flags.append("no-static-context-clue")
            elif selected_contexts and not matched_contexts:
                flags.append("no-exact-selected-context-path")
            if len(selected_contexts) > 1 and not matched_contexts:
                flags.append("multiple-selected-context-candidates")
            add_relation(
                "references-code",
                code_ref.artifact_id,
                target,
                "observed",
                "Code artifact was read as text and contains an exact selected-context path clue."
                if matched_contexts
                else (
                    "Code artifact was read as text and contains generic path or derivation clues, but no exact selected-context path."
                    if has_clue
                    else "Code artifact was read as text; no selected-context clue was observed."
                ),
                flags,
            )

    backup_variants = [variant for variant in variants if variant_has_backup_evidence(variant, json_payloads)]
    for variant in variants:
        add_relation(
            "has-variant",
            variant.artifact_id,
            bundle_id,
            "observed",
            "Variant manifest preserves branch ambiguity without importing full branch data.",
            ["manifest-only"],
        )
    for variant in backup_variants:
        add_relation(
            "has-backup",
            variant.artifact_id,
            bundle_id,
            "inferred",
            "Variant manifest includes backup-specific ambiguity at manifest level.",
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

    root_params_present = "parameters.json" in json_payloads
    root_params = json_payloads.get("parameters.json", {})
    for index, context in enumerate(selected_contexts, start=1):
        selected_params = json_payloads.get(context.path, {})
        selected_params_present = context.path in json_payloads
        conflict_id = "conflict-001" if index == 1 else f"conflict-001-{index}"
        if (
            root_params_present
            and selected_params_present
            and flatten_keys(root_params) != flatten_keys(selected_params)
        ):
            add_conflict(
                make_conflict(
                    conflict_id,
                    [by_path["parameters.json"].artifact_id, context.artifact_id],
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
                    conflict_id,
                    [by_path["parameters.json"].artifact_id, context.artifact_id],
                    "value-drift",
                    "active parameter source",
                    "Root parameters and selected settings share a shape but differ in values; the prototype must not choose a winner.",
                    "Ask the producer for selected settings path, selection reason, and freshness marker.",
                )
            )

    root_registry = json_payloads.get("registry.json", {})
    fallback_registry_artifact = by_path.get("setting/registry.json")
    if (
        fallback_registry_artifact is not None
        and fallback_registry_artifact.role not in SETUP_REGISTRY_FALLBACK_ROLES
    ):
        fallback_registry_artifact = None
    root_registry_present = "registry.json" in json_payloads
    selected_registry_artifacts = (
        setup_contexts
        if setup_contexts
        else ([fallback_registry_artifact] if fallback_registry_artifact else [])
    )
    for index, selected_registry_artifact in enumerate(selected_registry_artifacts, start=1):
        selected_registry = json_payloads.get(selected_registry_artifact.path, {})
        selected_registry_present = selected_registry_artifact.path in json_payloads
        conflict_id = "conflict-002" if index == 1 else f"conflict-002-{index}"
        if (
            root_registry_present
            and selected_registry_present
            and flatten_keys(root_registry) != flatten_keys(selected_registry)
        ):
            add_conflict(
                make_conflict(
                    conflict_id,
                    [by_path["registry.json"].artifact_id, selected_registry_artifact.artifact_id],
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
                    conflict_id,
                    [by_path["registry.json"].artifact_id, selected_registry_artifact.artifact_id],
                    "setup-value-drift",
                    "active setup registry",
                    "Root registry and selected registry share a shape but differ in values; this is setup-shaped evidence, not physical truth.",
                    "Ask whether setup evidence is selected, copied, session-injected, or stale.",
                )
            )

    for snapshot_index, snapshot in enumerate(copied_snapshots, start=1):
        snapshot_keys = flatten_keys(json_payloads.get(snapshot.path, {}))
        payload = json_payloads.get(snapshot.path, {})
        copied_from = payload.get("copied_from")
        normalized_copied_from = (
            normalize_declared_source_path(copied_from)
            if isinstance(copied_from, str)
            else None
        )
        if normalized_copied_from and by_path.get(normalized_copied_from) in selected_contexts:
            contexts_to_compare = [by_path[normalized_copied_from]]
        else:
            contexts_to_compare = selected_contexts
        for context_index, context in enumerate(contexts_to_compare, start=1):
            selected_keys = flatten_keys(json_payloads.get(context.path, {}))
            if selected_keys and not selected_keys <= snapshot_keys:
                conflict_id = "conflict-003"
                if snapshot_index > 1 or context_index > 1:
                    conflict_id = f"conflict-003-{snapshot_index}-{context_index}"
                add_conflict(
                    make_conflict(
                        conflict_id,
                        [snapshot.artifact_id, context.artifact_id],
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
            "Ask which bundle entry artifact was intended when the bundle was produced.",
        )

    if selected_contexts:
        add_missing_fact(
            "selected settings provenance",
            [selected.artifact_id for selected in selected_contexts],
            "Selected-looking context is visible but not authoritative.",
            "Ask whether settings path, selection reason, and producer timestamp exist.",
        )

    if generated_sidecars:
        add_missing_fact(
            "generated sidecar freshness",
            [sidecar.artifact_id for sidecar in generated_sidecars],
            "Derived files can be explained but not trusted as current without generation metadata.",
            "Ask whether generation source, generation time, and invalidation rule exist.",
        )

    if copied_snapshots:
        add_missing_fact(
            "snapshot coverage",
            [snapshot.artifact_id for snapshot in copied_snapshots],
            "Copied snapshots need explicit coverage before they can stand in for selected context.",
            "Ask whether copied snapshot source and coverage are known.",
        )

    if code_refs:
        add_missing_fact(
            "code identity",
            [code_ref.artifact_id for code_ref in code_refs],
            "Code-shaped evidence explains likely flow, but it is not an immutable code reference.",
            "Ask whether code origin or immutable reference exists before accepting code identity.",
        )

    for fact in missing_facts:
        affected_artifacts = fact["affected_artifacts"] or [bundle_id]
        for affected_artifact in affected_artifacts:
            add_relation(
                "missing-fact",
                affected_artifact,
                bundle_id,
                "missing",
                fact["user_impact"],
                [fact["fact_type"]],
            )

    add_relation(
        "redacts",
        bundle_id,
        "public-evidence-view",
        "generated",
        "Public-safe output preserves artifact roles and relation existence while avoiding sensitive source details.",
    )

    inventory = [
        {
            "artifact_id": artifact.artifact_id,
            "label": artifact.artifact_id,
            "public_label": artifact.artifact_id,
            "role": artifact.role,
            "status": public_artifact_status(
                artifact.status,
                artifact.role,
                artifact.sharing_boundary,
            ),
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
            "sharing_boundary": bundle_boundary,
            "redaction_policy_source": public_redaction_policy_source(
                manifest["redaction_policy"]["source"],
                bundle_boundary,
            ),
            "purpose": public_bundle_purpose(manifest["purpose"], bundle_boundary),
            "execution_boundary": "read JSON and code text only; do not import or execute fixture code",
            "mutation_boundary": "input fixture files are not modified",
        },
        "artifact_role_inventory": inventory,
        "selected_context_explanation": {
            "selected_context_candidate": selected_context.artifact_id if selected_context else None,
            "selected_context_candidates": [
                selected.artifact_id for selected in selected_contexts
            ],
            "setup_context_candidate": setup_context.artifact_id if setup_context else None,
            "setup_context_candidates": [setup.artifact_id for setup in setup_contexts],
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
            "observed_static_clues": {
                code_ref.artifact_id: code_clues[code_ref.path] for code_ref in code_refs
            },
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
            "backup_ambiguity_visible": bool(backup_variants),
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
                    "public_safe_replacement_label": artifact.artifact_id,
                }
                for artifact in artifacts
            ],
            "forbidden_content_categories": public_forbidden_content_categories(
                manifest["redaction_policy"]["forbidden_content"],
                bundle_boundary,
            ),
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
            selected_context_count=len(selected_contexts),
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
    selected_context_count: int,
) -> list[str]:
    next_checks: list[str] = []
    if len(anchors) != 1:
        next_checks.append("Ask which bundle anchor should be preferred, or preserve explicit alternatives.")
    if selected_context_count > 1:
        next_checks.append("Ask which selected-looking context applies, or preserve explicit alternatives.")
    if selected_context is not None:
        next_checks.append("Ask whether selected settings path, selection reason, and freshness marker exist.")
    if generated_sidecars:
        next_checks.append("Ask whether generated sidecar source and invalidation rules exist.")
    if copied_snapshots:
        next_checks.append("Ask whether snapshot source and coverage are known.")
    if code_refs:
        next_checks.append("Keep code references static until code identity ownership is accepted.")
    if readiness_hints:
        next_checks.append("Keep readiness hints static until managed execution boundaries are accepted.")
    return next_checks


def render_markdown(view: dict[str, Any]) -> str:
    public_labels = {
        artifact["artifact_id"]: artifact["artifact_id"]
        for artifact in view["artifact_role_inventory"]
    }

    def public_id(artifact_id: str | None) -> str | None:
        if artifact_id is None:
            return None
        return public_labels.get(artifact_id, artifact_id)

    def public_ids(artifact_ids: list[str]) -> str:
        return display_ids([public_id(artifact_id) or artifact_id for artifact_id in artifact_ids])

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
        artifact_label = artifact["public_label"]
        lines.append(
            f"| `{artifact_label}` | {artifact['role']} | "
            f"{artifact['evidence_handling']} | {artifact['sharing_boundary']} |"
        )

    lines.extend(
        [
            "",
            "## Selected-Context Explanation",
            "",
            "- Selected context candidate: "
            + display_value(public_id(view["selected_context_explanation"]["selected_context_candidate"])),
            "- Selected context candidates: "
            + public_ids(view["selected_context_explanation"]["selected_context_candidates"]),
            "- Setup context candidate: "
            + display_value(public_id(view["selected_context_explanation"]["setup_context_candidate"])),
            "- Setup context candidates: "
            + public_ids(view["selected_context_explanation"]["setup_context_candidates"]),
            f"- Status: {view['selected_context_explanation']['status']}",
            "",
            "## Generated And Copied Relation Summary",
            "",
            "- Generated sidecars: " + public_ids(view["generated_and_copied_relation_summary"]["generated_sidecars"]),
            "- Copied snapshots: " + public_ids(view["generated_and_copied_relation_summary"]["copied_snapshots"]),
            "",
            "Relation inventory:",
            "",
            "| Type | Source | Target | Evidence | Reason | Flags |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )

    for relation in view["relations"]:
        lines.append(
            f"| {relation['relation_type']} | `{public_id(relation['source_artifact'])}` | "
            f"`{public_id(relation['target_artifact'])}` | {relation['evidence_handling']} | "
            f"{relation['confidence_narrative']} | "
            f"{display_flags(relation['flags'])} |"
        )

    lines.extend(
        [
            "",
            "## Code-Reference Summary",
            "",
            "- Code references: " + public_ids(view["code_reference_summary"]["code_references"]),
            f"- Execution boundary: {view['code_reference_summary']['execution_boundary']}",
            "",
            "## Static Readiness Hint Summary",
            "",
            "- Readiness hints: " + public_ids(view["readiness_hint_summary"]["readiness_hints"]),
            "",
            "## Variant, Backup, And Unknown Artifact Summary",
            "",
            "- Variant artifacts: " + public_ids(view["variant_backup_unknown_summary"]["variant_artifacts"]),
            f"- Backup ambiguity visible: `{view['variant_backup_unknown_summary']['backup_ambiguity_visible']}`",
            "- Unknown artifacts: " + public_ids(view["variant_backup_unknown_summary"]["unknown_artifacts"]),
            "",
            "## Conflict And Missing-Fact Report",
            "",
            "| ID | Type | Artifacts | Implication | Next check |",
            "| --- | --- | --- | --- | --- |",
        ]
    )

    for item in view["conflict_and_missing_fact_report"]["conflicts"]:
        lines.append(
            f"| `{item['conflict_id']}` | {item['conflict_type']} | "
            f"{public_ids(item['artifacts'])} | "
            f"{item['user_visible_implication']} | {item['next_check']} |"
        )

    lines.extend(
        [
            "",
            "| ID | Type | Affected artifacts | Impact | Suggested next check |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for item in view["conflict_and_missing_fact_report"]["missing_facts"]:
        lines.append(
            f"| `{item['fact_id']}` | {item['fact_type']} | "
            f"{public_ids(item['affected_artifacts'])} | "
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

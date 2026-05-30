# Handoff Package Route Contract Checklist

## Status

Retired discovery coordination note for the handoff package route.

This is not accepted architecture, a final package schema, user documentation, or
a shared measurement-record domain model. It records the historical
route-local contract discipline that was applied while adding or reviewing
handoff package discovery slices. Current runtime handoff checks live in
route-private `scopecat/handoff/_contracts.py`; current implementation
boundaries live in the handoff architecture and module docs.

## Purpose

Recent handoff-package reviews repeatedly found the same class of issue:
fields were emitted or passed between slices before their semantic category and
validator were explicit. Use this checklist to classify same-class fields
together instead of fixing one reviewed example at a time.

Historical discovery helpers live in
`implementation_candidates/handoff_package_contracts/`. The promoted local
handoff implementation now owns its runtime handoff checks under route-private
`scopecat/handoff/_contracts.py`. Treat the candidate helpers as discovery
evidence unless a future slice explicitly reuses them as evidence. Slice
policy, file-system effects, and workflow ordering stay local to each
candidate or accepted route implementation.

## Field Categories

Every field that crosses a handoff-package slice boundary should be classified
before it is emitted:

| Category | Meaning | Current handling |
| --- | --- | --- |
| Managed identifier | Program-owned id used as a package id, source id, record id, link id, relation, role, or schema-binding name. | Validate with public-safe identifier grammar before output. |
| Managed package path | Program-owned package-relative reference. | Validate exact topology where known and public-safe path segments for every packaged managed reference; do not accept fixture-driven arbitrary nesting. |
| Redacted display reference | Local/review display for a managed object, not a portable package path. | Validate with a generated redacted-display shape; omit from portable writer manifests unless explicitly accepted. |
| Free text | Human label, display name, note, or reason. | Validate as text only; public fixtures must be reviewed for safe text, but do not add broad runtime redaction by default. |
| Declared manifest fact | Digest, size, preview metadata, package state, or package policy declared by the manifest. | Validate syntax and policy shape; do not claim observation or integrity unless a slice performs that check. |
| Observed table fact | Rows and columns loaded from an opened package member. | Keep string-valued and rectangular; require unique non-empty headers and reject ragged rows before presenting a table-like read surface. |
| Local receipt fact | Return value for engineering review of a local operation. | Keep local/review-only unless a slice explicitly promotes it to a portable artifact. |
| Local operation path | Storage-relative or package-root-relative path used to perform or review a local write/open operation. | Keep in local receipts; do not project into portable manifests unless converted to a managed package path. |

## Current Route Checks

| Surface | Fields | Category | Current owner/check |
| --- | --- | --- | --- |
| Package identity | `package_id`, `source_export_summary_id` | Managed identifier | Writer, composition, contents preview, and opener via contents-preview reuse validate public-safe identifiers. |
| Package identity | `created_by` | Fixed managed literal | Must remain `scopecat_selected_measurement_export`. |
| Package identity | `display_name` | Free text | Validate as text; do not scan for path-like label content by default. |
| Package identity | `display_path` | Redacted display reference | Validate as `HANDOFF_PACKAGE:/redacted/{id}` where present; writer omits it from the portable manifest, and composition must accept that absence. |
| Package identity | `local_path_redacted` | Declared manifest fact | Must be `true` for package preview/open surfaces. |
| Selected measurements | `selected_measurements` | Route content contract | Must be non-empty for writer, contents preview, and opener. |
| Selected measurements | `measurement_record_id` | Managed identifier | Validate public-safe identifiers and uniqueness before using as path segments or targets. |
| Primary package data | `primary_data.package_path`, primary bundle path, plot source | Managed package path | Current package topology is exactly `measurements/{measurement_record_id}/primary.csv`; additional package member layouts need separate contracts. |
| Primary package data | `digest`, `size_bytes` | Declared manifest fact | Validate sha256 syntax and positive size where declared; opener reports them without comparing by default. |
| Opened primary table | `primary_table.columns`, `primary_table.rows` | Observed table fact | Opener emits local string-valued table facts only after reading package-local CSV with unique non-empty headers and rectangular rows. Read-view wraps these facts without adding dataframe, type-inference, or large-file semantics. |
| Preview metadata | `status`, declared columns, plot candidates | Declared manifest fact and managed schema-binding names | Contents preview accepts `preview_ready` and `degraded_preview`; opener currently opens only `preview_ready`. |
| Linked context | `link_id`, `kind`, `relation`, linked measurement targets | Managed identifiers and target references | Writer, composition, contents preview, and opener via contents-preview reuse validate managed shape and selected-target alignment. |
| Linked context | `label`, `reason` | Free text | Validate as text where owned by writer/composition; keep public fixtures reviewed. |
| Linked context | `package_state`, `package_path` | Declared manifest fact and managed package path | Contents preview can describe manifest-declared packaged context without file reads, but packaged paths still need public-safe segments under `context`; writer/opener currently keep linked context reference-only. Payload writing or opening needs a separate contract. |
| Opener file reads | package root, manifest, primary CSV path | Managed filesystem boundary | Opener rejects symlink package roots, primary files, and primary parent directories, but does not claim adversarial race safety. |
| Integrity/import/storage | checksum comparison, archive extraction, import acceptance, storage mutation | Explicitly separate workflows | Keep `not_performed` or `not_claimed` unless a slice performs that workflow. |
| Writer receipt | `source_path`, `package_write_request`, materialized paths | Local operation path | Writer validates them for the local operation and keeps them in the local write receipt, not the portable manifest. |
| Receiving workflow roots | package root, storage root, local artifact output root and fixed artifact target | Managed filesystem boundary | Receiving workflow validates root separation and the concrete local artifact target before local artifact writes or storage acceptance. This is provisional preflight separation, not concurrent mutation protection or a storage architecture. |
| Receiving reviewed facts | reviewed package id, preview classification, integrity classification | Route-local contract support | Receiving workflow validates reviewed facts against inspection and integrity-observation facts before acceptance. This is provisional fact continuity, not workflow orchestration or GUI state. |
| Shared route helpers | package identity, package item shape, primary-data topology, preview-ready metadata, provisional receiving root separation, provisional reviewed fact continuity | Route-local contract support | The accepted local handoff implementation uses route-private `scopecat/handoff/_contracts.py`. Historical `handoff_package_contracts` candidates remain discovery evidence for slices that have not been promoted. Do not use either surface to promote a final package schema, storage architecture, or SDK object model. |

## Review Requirements

For new handoff-package changes:

1. Classify every new emitted field using the categories above.
2. Validate managed identifiers, managed package paths, redacted display
   references, declared digests, declared sizes, and target lists before output.
3. Treat labels, display names, and reasons as free text unless the slice
   explicitly adds a redaction policy surface.
4. Add at least one negative test for each new managed category or boundary
   narrowing.
5. When a reviewer finds one unvalidated managed field, audit same-class fields
   in the same surface before patching.
6. Keep positive docs current: say what the slice validates before listing what
   remains outside the boundary.

## Extraction Boundary

This checklist justifies shared low-level primitives and route-local helper
contracts, not a shared package or measurement domain model. Promote a fuller
model only when multiple validated slices need the same object lifecycle and
behavior, not just the same field shape checks.

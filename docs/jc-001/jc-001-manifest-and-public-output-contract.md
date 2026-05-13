# JC-001 Manifest And Public Output Contract

## Status

Fixture validated for the `JC-001` passive evidence-view prototype.

## Purpose

Document the manifest, public identity, and public-output redaction contract
currently enforced by
[`../../prototypes/jc001_passive_evidence_view.py`](../../prototypes/jc001_passive_evidence_view.py)
and validated by
[`../../tests/test_jc001_passive_evidence_view.py`](../../tests/test_jc001_passive_evidence_view.py).

This contract is scoped to the accepted
[`JC-001` passive evidence-view boundary](jc-001-passive-evidence-view-decision.md)
and the committed public-safe fixtures. It is not a general fixture format,
sample-data policy, support-export policy, internal diagnostics policy, parser
framework, durable storage schema, or public user-documentation contract.

## Contract Boundary

The current prototype accepts one fixture directory containing:

- `fixture-manifest.json`;
- JSON artifacts listed by the manifest;
- static code text artifacts listed by the manifest.

The prototype emits:

- `evidence-view.json`;
- `evidence-view.md`.

The manifest and output contract exists to keep fixture-scale passive
explanation public-safe while preserving artifact roles, relation existence,
conflicts, missing facts, and redaction evidence. It does not claim to import
arbitrary legacy folders or define how future producers should write durable
records.

## Manifest Shape

`fixture-manifest.json` must be an object with:

| Field | Required | Meaning |
| --- | --- | --- |
| `fixture_id` | Yes | Source fixture identifier used as source material, not directly emitted when unsafe. |
| `public_bundle_id` | Yes | Fixture-authored public bundle identifier emitted in public output. |
| `purpose` | Yes | Fixture purpose text; redacted from public output when the bundle boundary is redaction-sensitive. |
| `redaction_policy.source` | Yes | Source of redaction policy metadata; redacted from public output when the bundle boundary is redaction-sensitive. |
| `redaction_policy.forbidden_content` | Yes | List of source content categories to avoid leaking; emitted only as public-safe or redacted category text. |
| `artifacts` | Yes | Non-empty list of manifest-listed artifacts. |

Each artifact entry must include:

| Field | Required | Meaning |
| --- | --- | --- |
| `path` | Yes | Fixture-local path to an artifact. |
| `public_id` | Yes | Fixture-authored public artifact identifier emitted in JSON and Markdown output. |
| `role` | Yes | Role normalized to the first-wedge role vocabulary or `unknown`. |
| `status` | Yes | Source status text; redacted from public output for redaction-sensitive artifacts. |
| `evidence_handling` | Yes | First-wedge evidence handling value. |
| `sharing_boundary` | Yes | Public-output boundary for the artifact. |

## Controlled Values

Allowed `sharing_boundary` values for this prototype are:

- `public-safe`;
- `redaction-sensitive`.

Allowed `evidence_handling` values are:

- `observed`;
- `inferred`;
- `generated`;
- `copied`;
- `user-declared`;
- `unchecked`;
- `unsafe-to-inspect`;
- `missing`.

The prototype does not currently accept `internal-safe`,
`external-support-safe`, or `unsafe-to-share` artifacts. Those are follow-on
sharing-policy decisions.

## Fixture-Local Path Rules

Manifest paths must:

- resolve inside the fixture directory;
- point to existing files;
- not escape through `..` or symlinks;
- be unique as manifest paths;
- not produce duplicate generated raw artifact IDs.

The fixture manifest itself must also resolve inside the fixture directory.

## Public Identity Rules

The prototype emits `public_bundle_id` and artifact `public_id` values as the
public JSON/Markdown identities. It does not emit source-derived path labels as
public labels.

All public IDs must match the public-safe slug pattern:

```text
^[a-z0-9][a-z0-9_-]*$
```

Public-safe artifacts:

- must provide an explicit `public_id`;
- must not use a `redacted-` prefix;
- must not include source-derived text from fixture ID, purpose, redaction
  policy source, forbidden-content categories, artifact paths, artifact status,
  JSON payloads, or code text.

Redaction-sensitive artifacts:

- must provide an explicit `public_id`;
- must use the role-prefixed form:

```text
redacted-<normalized-role-with-dashes>-<fixture-authored-handle>
```

- must use a short fixture-authored handle;
- must not use source-derived text;
- must not look hash-derived.

Redaction-sensitive bundle IDs:

- must use the prefix `redacted-work-bundle-`;
- must use a short fixture-authored handle;
- must not use source-derived text;
- must not look hash-derived.

Public artifact IDs must not collide with the emitted bundle ID or with other
emitted artifact IDs.

## Public Output Redaction Rules

For `public-safe` output:

- public artifact IDs and bundle IDs are emitted as fixture-authored public
  handles;
- artifact roles and relation existence are preserved;
- manifest purpose and redaction-policy source are replaced with public-safe
  retained-in-fixture text;
- forbidden-content categories are summarized as public-safe fixture category
  text.

For `redaction-sensitive` output:

- source artifact labels, source paths, source-derived statuses,
  redaction-policy metadata, bundle metadata, and payload/code-derived text are
  redacted from JSON and Markdown output;
- public output preserves the existence and role of redacted evidence;
- relation targets use fixture-authored redaction handles rather than source
  labels, source-derived hashes, or manifest-order labels;
- unknown or unsafe evidence remains visible as redacted evidence instead of
  disappearing.

## Diagnostic Fields

The prototype may include fixture/test-oriented fields such as
`static_shape_checks` in `evidence-view.json`. These fields are diagnostic for
prototype validation. They are not accepted as a public product API or durable
storage schema.

## Deferred Scope

This contract does not define:

- internal-safe diagnostic output;
- external-support-safe export;
- unsafe-to-share export behavior;
- legal or institutional redaction policy;
- public documentation examples;
- arbitrary legacy-folder import;
- notebook or opaque binary semantic handling;
- durable manifest versioning;
- product API stability.

Any future journey that needs those behaviors must either reopen this contract
or create a separate evidence-backed sharing/export decision.

## Acceptance Checks

A future change to this contract must preserve these checks unless a new
accepted decision changes the boundary:

- manifest fields required by the prototype remain explicit;
- artifact paths stay fixture-local;
- duplicate manifest paths and duplicate emitted IDs are rejected;
- public IDs are explicit, fixture-authored, stable, and non-source-derived;
- redaction-sensitive IDs use role-prefixed redaction handles;
- hash-like handles are rejected;
- source-derived text from metadata, payloads, and code is not emitted in
  public JSON or Markdown;
- public output preserves role and relation existence under redaction;
- unsupported sharing boundaries are rejected instead of silently accepted;
- generated output remains JSON and Markdown only.

## Reopen When

Reopen this contract when:

- another fixture family needs a manifest field not represented here;
- another journey needs internal-safe, external-support-safe, or unsafe-to-share
  output;
- public output needs stable product API semantics rather than prototype
  diagnostics;
- public-safe redaction loses too much diagnostic value for the validated
  journey;
- implementation behavior diverges from this contract.

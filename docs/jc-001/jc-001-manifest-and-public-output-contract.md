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
| `status` | Yes | Source status text used for fixture validation; public output emits a retained-in-fixture or redacted status rather than the source status text. |
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

### Role Normalization

Manifest roles are normalized before they are used in public IDs, relation
generation, and report sections.

| Manifest role | Normalized role |
| --- | --- |
| `anchor` | `anchor` |
| `selected-context candidate` | `selected context` |
| `selected context` | `selected context` |
| `fixture-authored` | `fixture-authored` |
| `setup evidence` | `setup evidence` |
| `generated sidecar` | `generated sidecar` |
| `run-bound copied snapshot` | `copied snapshot` |
| `copied snapshot` | `copied snapshot` |
| `variant` | `variant` |
| `code-shape evidence` | `code reference` |
| `code reference` | `code reference` |
| `readiness hint` | `readiness hint` |
| any other role | `unknown` |

`generated sidecar` is fixture vocabulary for this prototype. Broader product
docs should prefer `companion artifact` unless they are describing this
specific fixture role.

## Fixture-Local Path Rules

Manifest paths must:

- resolve inside the fixture directory;
- point to existing files;
- not escape through `..` or symlinks;
- be unique as manifest paths;
- not produce duplicate generated raw artifact IDs.

The fixture manifest itself must also resolve inside the fixture directory.

## Artifact Read Behavior

The prototype infers artifact read behavior from path and normalized role:

- paths ending in `.json` are parsed as JSON artifacts;
- normalized `code reference` artifacts are read as static UTF-8 text;
- code text is never imported or executed;
- opaque non-JSON artifacts are not semantically inspected by this contract.

Future fixtures that need notebooks, binary artifacts, non-JSON text artifacts,
or unusual suffixes must reopen this contract or create a separate fixture
contract.

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

Public-safe bundle IDs:

- must provide an explicit `public_bundle_id`;
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

Fixture-authored redaction handles use the stricter handle pattern:

```text
^[a-z][a-z0-9]{0,7}$
```

The prototype rejects handles that look hash-derived with six to eight
hexadecimal characters, match source raw IDs, include source tokens of four or
more characters, or partially overlap with longer source tokens. Common file
extension tokens such as `json`, `txt`, `py`, and `md` are ignored for this
source-token check.

## Relation Generation Rules

The current fixture-scale relation rules are part of this contract:

- selected-context artifacts get `appears-selected-for` relations to the
  bundle, with static-code support when an exact selected-context path clue is
  found;
- setup evidence gets `appears-selected-for` relations to the bundle and stays
  non-authoritative physical context evidence;
- generated sidecars use a JSON `generated_from` field when present, falling
  back to selected-context artifacts or the bundle as redacted evidence;
- copied snapshots use a JSON `copied_from` field when present, falling back to
  selected-context artifacts or the bundle as redacted evidence;
- code references are text-only `references-code` evidence and target exact
  selected-context path matches when present;
- root `parameters.json` is compared with selected-context JSON artifacts for
  shape drift and value drift conflicts;
- root `registry.json` is compared with setup-context artifacts, or with
  `setting/registry.json` when that artifact normalizes to selected context or
  setup evidence;
- variant artifacts preserve branch and backup ambiguity without choosing a
  winner.

These rules are accepted for `JC-001` fixture validation only. They are not a
general parser framework or durable relation engine.

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

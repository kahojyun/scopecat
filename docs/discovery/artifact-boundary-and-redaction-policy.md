# Artifact Boundary and Redaction Policy

## Status

Discovery policy rule, not an ADR.

This note defines how discovery fixtures, summaries, review artifacts, local
Scopecat UI surfaces, and future portable/export/package outputs should carry
redaction responsibility. It exists to prevent every validation slice from
becoming a broad runtime redaction or DLP system.

## Rule

Discovery fixtures and expected outputs must be **repository-safe** by default,
not necessarily **portable/export-safe**.

Scopecat optimizes for usefulness inside the user's local/lab context. Runtime
redaction is not required merely because a value appears in a local Scopecat UI,
internal review summary, or discovery summary; users need to inspect their own
paths, labels, and context to make the tool useful.

Runtime redaction is required only at a declared portable/public/export
boundary. If an artifact is exported outside the repository or local workspace,
published, attached to public documentation, materialized as a portable handoff
artifact, or otherwise generated to be carried away or shared, treat it as a
portable/public/export boundary even when the slice did not explicitly label
it.

Discovery candidates should not recursively scan every string by default.
Instead, they should validate the Scopecat-managed references that the slice
claims to own. Deliberate projection and typed contract checks are contract
hygiene, not a demand for broad runtime redaction. Keep broad free-text
redaction out of scope unless the slice explicitly accepts a redaction policy
surface.

## Artifact Classes

| Class | Meaning | Redaction responsibility |
| --- | --- | --- |
| Repository-safe fixture artifact | Test input, expected output, or discovery evidence committed to this repository. | Must not contain real secrets, real private paths, real hostnames, real lab/user/customer identifiers, tokens, or accidental local filesystem leaks. Synthetic sensitive-shaped examples may appear only when intentionally testing boundary behavior. Synthetic absolute paths that are not sensitive-shaped should be clearly fake and should not resemble a real user, lab, host, or customer environment. |
| Internal validation output | Program state or candidate output used to test a slice-local contract. | May preserve synthetic raw facts needed for validation when repository-safe. It should not be documented as portable/public/export output. |
| Review summary or local UI surface | A structured summary or UI view meant for the local Scopecat user, developer, or reviewer inspecting their own data. | Should be useful and deliberate: avoid dumping unrelated raw nested input, validate managed references it exposes, and preserve the information needed for local inspection. It does not need runtime redaction merely because it is visible in the app. |
| Portable/public/export artifact | Exported package manifest, package writer output, externally published documentation, externally shared report, or package-writer/generated handoff artifact intended to be carried away or shared. | Must own the portable/export projection, redaction rules, package-relative references, materialization destinations, and integrity expectations for that artifact. |

## Managed References

Scopecat-managed references require strict validation when a slice claims to
own or transform them:

- storage-relative paths;
- package-relative paths;
- source identities and external-root displays;
- materialization destinations;
- relation targets;
- package member references;
- generated artifact identifiers that become links, paths, or package entries.

This is reference validation, not broad text redaction. User-authored labels,
display names, notes, descriptions, and messages remain free text unless a
slice explicitly defines a redaction policy surface or generates a portable/
public/export artifact. Repository fixtures should still be reviewed for safe
wording.

## Discovery Summary Posture

A discovery `summary` is not automatically portable/public/export output. It
should declare one of these postures in its README, validation result, or
summary policy field:

- **internal validation summary**: repository-safe fixture artifact, not a
  portable/public/export boundary;
- **review summary**: local-user/reviewer projection that avoids unrelated raw
  passthrough and validates exposed managed references, without treating local
  UI visibility as a redaction boundary;
- **export/package summary or manifest**: portable/export boundary with
  explicit package/public redaction and reference rules.

If a summary returns a whole raw input object, that object becomes part of the
summary's artifact boundary. Raw passthrough is acceptable only for a documented
internal validation summary when the fixture remains repository-safe and the
artifact is not a review projection or portable/export artifact. Prefer
deliberate projections for review and export summaries.

## Package Writer Boundary

The future package writer is the strongest portable/export boundary for
measurement handoff. It should own final package redaction, package-relative
paths, manifest public safety, materialization decisions, and package
integrity.

Earlier discovery candidates may preview package-shaped facts, but preview
does not make every upstream slice responsible for final package redaction.

## Composition Slices

Composition candidates should distinguish:

- raw fixture/interchange input;
- candidate-local contract checks for the selected facts used in composition;
- adapters into child slice input shapes;
- the summary projection they return.

When a composition slice consumes another candidate's output, it should not
assume responsibility for all possible fields in that candidate unless it
returns them. If it returns only a projection, it validates only the managed
references and state needed for that projection.

## Non-Goals

This rule does not accept:

- a final product redaction engine;
- a JSON Schema for all discovery fixtures;
- recursive DLP scanning for every string in every candidate;
- portable/export status for all expected-output fixtures;
- a shared measurement-record model.

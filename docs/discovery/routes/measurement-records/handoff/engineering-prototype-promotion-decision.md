# Handoff Engineering Prototype Promotion Decision

## Status

Engineering promotion decision, not an ADR.

Artifact posture: `internal_validation_summary`. This note is internal project
memory. It creates no portable package output, public contract, public SDK, or
new redaction rule. Use
[`policies/artifact-boundary-and-redaction.md`](../../../policies/artifact-boundary-and-redaction.md)
if any accepted implementation output is later promoted into a
portable/export artifact.

## Decision

Promote the read-only handoff engineering prototype as the accepted baseline
for the handoff route's first implementation vertical:

```text
package directory
  -> manifest validation and preview classification
  -> read-only package open
  -> package, measurement, table, declared plot, linked-context, and finding access
  -> local CLI or static HTML review surface
```

This promotion stops the current engineering prototype line. Further work on
the same route should be either:

- small maintenance on the accepted read-only vertical;
- PR/release preparation for the current branch;
- a separately scoped route extension triggered by the reopen conditions in
  [`decision.md`](decision.md).

It should not continue as broad prototype expansion.

## Accepted Baseline

The promoted baseline includes:

- the route-local `scopecat/handoff/` module boundary;
- `open_package(package_dir)` as the Python entrypoint;
- `python -m scopecat.handoff <package-dir>` as the local CLI entrypoint;
- route-private manifest validation and preview classification;
- typed route-local manifest fragments after raw JSON/dict validation;
- product-shaped route projections for package, measurement, tables, declared
  plot series, findings, and linked context;
- read-only package-local primary CSV opening for `preview_ready`
  measurements;
- declared preview metadata as the preview authority;
- package-id and package-directory continuity;
- canonical primary-data topology,
  `measurements/{measurement_record_id}/primary.csv`;
- linked context as visible reference-only review state;
- local static HTML as the first review artifact;
- representative regression coverage over basic and route-pressure fixtures.

## Explicit Non-Promotions

This decision does not promote:

- final public SDK names or package publishing metadata;
- hard pandas/numpy dependency;
- matplotlib, production plotting, or publication-grade rendering;
- live GUI components, routing, or interaction model;
- numeric dtype conversion, unit conversion, schema inference, scan-shape
  inference, trace opening, or array API;
- archive extraction, compressed package format, signatures, authenticity,
  trust policy, or adversarial package-root race handling;
- storage import, acceptance, conflict policy, or existing-record update;
- linked-context payload packaging, opening, recursive traversal, or import;
- analysis/fit result model, fit execution, uncertainty, write-back, or result
  import;
- shared measurement-record domain model or cross-route object lifecycle.

## Discovery Candidate Posture

Existing handoff implementation candidates remain historical discovery
evidence. They should not be treated as runtime dependencies for the promoted
read-only vertical.

Do not rewrite old candidate validation results only to match the promoted
implementation shape. Update old candidates only when preserving their
historical tests requires it, or when a future route extension explicitly
chooses to reuse one as evidence.

## Maintenance Rule

Future changes to the accepted read-only vertical should preserve the current
boundary:

- raw JSON/dict handling stays at the manifest/package boundary;
- route-private modules with leading underscores are not public SDK or
  cross-route domain APIs;
- runtime redaction is required only at declared or effective portable/export
  boundaries;
- static HTML remains a local review surface, not a public report format;
- external dependencies require a concrete workflow trigger.

## Resume Triggers

Resume handoff work only when a named workflow needs one of the deferred
capabilities, such as:

- notebook computation requiring numeric/dataframe adapters;
- GUI review requiring interaction beyond static HTML;
- external sharing requiring archive/signature/trust behavior;
- durable local import requiring storage acceptance and conflict policy;
- inspectable linked-context payloads;
- analysis or fit results becoming first-class read-only display facts;
- another route needing identical lifecycle and failure semantics, justifying
  a narrower shared-model decision.

## Verification

Promotion was made after the engineering readiness assessment in
[`engineering-prototype-readiness.md`](engineering-prototype-readiness.md) and
should be preserved with:

```text
uv run python -m unittest discover -s tests
uv run prek run --all-files
```

# Selected Reference Comparison Validation Result

## Status

Fixture-level validation result, not an ADR.

This result records what the selected-reference fixtures proved and where the
boundary remains intentionally narrow.

## Fixtures

- `tests/fixtures/selected_reference_comparison/basic_context_compare/`
- `tests/fixtures/selected_reference_comparison/code_version_context_compare/`

The first fixture validates a selected-reference comparison boundary:

- a reference can be user-selected through an ordinary mark;
- user marks can supply reference labels such as last-working without special
  Scopecat reference semantics;
- current and reference measurements can be paired by explicit IDs;
- named input snapshots can be compared as context;
- setup binding can be same-observed while parameter state changes;
- matching declared preview metadata can be shown as objective context;
- matching declared preview metadata can pressure future quick browsing or
  overlay of compatible measurements without committing to publication-grade
  plotting;
- missing, unlinked, unverified, redacted, changed, same-observed, and
  not-compared scope can stay distinct;
- the report can avoid using `gap` as a catch-all.

It intentionally does not include experiment code/version context.

The code-version fixture adds the next narrow comparison dimension:

- measurements can reference recorded code context as a named input;
- recorded code context IDs and captured code-version record identities can be
  compared as declared context;
- matching entrypoint paths and notebook recording policy can be shown as
  same-observed findings;
- changed recorded source observations can be surfaced without claiming Git
  diff, semantic source review, checksum, archive, or content-addressed
  storage contracts;
- include-list inventory changes can distinguish helpers missing on current from
  helpers missing on reference;
- declared environment refs can match while environment readiness remains not
  compared;
- redacted external code roots can remain public-safe context;
- internal Git state, dependency closure, code execution, managed workspace
  restore, and workflow/DAG behavior remain out of scope.

## Boundary Confirmed

Selected-reference comparison is a context comparison report. It is not a
user-judgment engine.

The useful first output is a compact findings summary that helps a reviewer see
what changed and what is unavailable. It does not:

- explain why data changed;
- inspect raw waveforms;
- compare fit quality;
- prove physical setup truth;
- interpret user-provided analysis conclusions;
- inspect internal Git state or live files;
- resolve dependency closure or environment readiness;
- restore, load, import, or execute recorded code;
- compare source semantics beyond declared recorded-code observations.

The reference-selection model can start from ordinary measurement marks. A
user may mark a run as last-working, notable, best-observed, or simply
relevant. Selected-reference comparison can compare against that marked run
without Scopecat needing special semantics for each label.

## Relationship To Prior Slices

These fixtures reuse validated pressure without promoting shared architecture:

- selected export contributes explicit measurement selection;
- running inspection contributes declared preview metadata;
- parameter state contributes selected parameter-state context;
- setup binding contributes selected setup-binding and station-registry
  context.
- experiment code recording contributes recorded-code context, include-list
  recording policy, stripped notebook source posture, declared refs, and
  captured code-version record identity shape.

The fixtures use named inputs because that vocabulary is useful, but they do
not earn a shared run-context framework. The code-version fixture also uses
recorded source observation IDs as fixture-level comparison tokens; it does
not earn a checksum, archive, content-addressed storage, or final integrity
contract.

## Remaining Risks

- the finding vocabulary may need more examples before it becomes a product
  warning taxonomy;
- reference selection UX is still undecided;
- quick plot preview comparison is future GUI pressure, not a plotting-quality
  contract;
- raw-data and fit-quality comparison remain separate future slices;
- user scripts or humans may still make higher-level judgments from Scopecat
  records, but that is outside this fixture;
- experiment code/version mismatch can be compared as declared recorded-code
  context, but source semantics, restore readiness, environment readiness,
  dependency closure, Git state, and code execution remain separate risks;
- recipient-aware redaction remains broader than this fixture.

## Current Recommendation

Stop this slice at fixture validation unless a near-term task needs a
production-shaped summary candidate. Use the fixture as comparison pressure
when designing measurement run context, selected references, and future
review/report surfaces. Treat code-version comparison as declared context
comparison only: recorded code context, captured code-version record identity,
include-list inventory, recorded source observations, and declared refs. Do not
promote it into managed workspace storage, Git analysis, environment restore,
selected-version loading, code execution, semantic source diff, or workflow
contracts.

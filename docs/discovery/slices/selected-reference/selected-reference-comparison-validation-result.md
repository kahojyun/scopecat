# Selected Reference Comparison Validation Result

## Status

Implementation candidate validated, not an ADR.

This result records what the selected-reference fixtures proved and where the
side-effect-free implementation candidate keeps the boundary intentionally
narrow.

## Fixtures

- `tests/fixtures/selected_reference_comparison/basic_context_compare/`
- `tests/fixtures/selected_reference_comparison/code_context_compare/`
- `tests/fixtures/resolved_context_link_comparison/basic_selected_reference/`

Implementation candidate:
`implementation_candidates/selected_reference_comparison/`

Candidate tests:
`tests/test_selected_reference_comparison_summary_candidate.py`

The first fixture and summary builder validate a selected-reference comparison
boundary:

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

It intentionally does not include experiment code context.

The code-context fixture and summary builder add the next narrow comparison
dimension:

- measurements can reference recorded code context as a named input;
- recorded code context IDs and code snapshot record identities can be
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

The resolved-context-link fixture and summary builder add a measurement-context
subcase:

- selected-reference comparison can use actual measurement-record context
  links rather than prospective measurement intent selectors;
- changed parameter state, same setup binding, same managed code version, and
  missing current declared environment context can be reported as objective
  context-link findings;
- context payloads, primary data, fit quality, readiness, and cause
  attribution remain out of scope.

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
- restore, load, import, or execute selected code snapshots;
- compare source semantics beyond declared recorded-code observations.

The reference-selection model can start from ordinary measurement marks. A
user may mark a run as last-working, notable, best-observed, or simply
relevant. Selected-reference comparison can compare against that marked run
without Scopecat needing special semantics for each label.

## Relationship To Prior Slices

These fixtures and summary builders reuse validated pressure without promoting
shared architecture:

- selected export contributes explicit measurement selection;
- running inspection contributes declared preview metadata;
- parameter state contributes selected parameter-state context;
- setup binding contributes selected setup-binding and station-registry
  context.
- experiment code recording contributes recorded-code context, include-list
  recording policy, stripped notebook source posture, declared refs, and
  code snapshot record identity shape.

The implementation candidate uses named inputs because that vocabulary is
useful, but it does not earn a shared run-context framework. The code-context
builder also uses recorded source observation IDs as fixture-level comparison
tokens; it does not earn a checksum, archive, content-addressed storage, or
final integrity contract.

Future code comparison should be treated as a fixture family rather than a
single selected-version comparison engine. Recorded context comparison,
snapshot capture-state comparison, managed-version inventory comparison, and
editable-folder observation may share finding vocabulary only where their
authority and capture-state behavior match.

Resolved context-link comparison belongs to the measurement-context backlog
because its authority is the measurement record's resolved links. It should not
be generalized into intent-selector comparison or cause attribution.

## Remaining Risks

- the finding vocabulary may need more examples before it becomes a product
  warning taxonomy;
- reference selection UX is still undecided;
- quick plot preview comparison is future GUI pressure, not a plotting-quality
  contract;
- raw-data and fit-quality comparison remain separate future slices;
- user scripts or humans may still make higher-level judgments from Scopecat
  records, but that is outside this fixture;
- experiment code-context mismatch can be compared as declared recorded-code
  context, but source semantics, restore readiness, environment readiness,
  dependency closure, Git state, and code execution remain separate risks;
- recipient-aware redaction remains broader than this fixture.

## Slice Recommendation

Stop this slice at the side-effect-free implementation candidate. Use the
candidate as comparison pressure when designing measurement run context,
selected references, and future review/report surfaces. Treat code-context
comparison as declared context comparison only: recorded code context, code
snapshot record identity, include-list inventory, recorded source observations,
and declared refs. Do not promote it into managed workspace storage, Git
analysis, environment restore, selected-version loading, code execution,
semantic source diff, or workflow contracts.

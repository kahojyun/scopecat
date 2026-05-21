# Selected Reference Comparison Validation Result

## Status

Fixture-level validation result, not an ADR.

This result records what the first selected-reference fixture proved and where
the boundary remains intentionally narrow.

## Fixture

- `tests/fixtures/selected_reference_comparison/basic_context_compare/`

The fixture validates a first selected-reference comparison boundary:

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
  not-compared findings can stay distinct;
- the report can avoid using `gap` as a catch-all.

## Boundary Confirmed

Selected-reference comparison is a context comparison report. It is not a
user-judgment engine.

The useful first output is a compact findings summary that helps a reviewer see
what changed and what is unavailable. It does not:

- explain why data changed;
- inspect raw waveforms;
- compare fit quality;
- prove physical setup truth;
- interpret user-provided analysis conclusions.

The reference-selection model can start from ordinary measurement marks. A
user may mark a run as last-working, notable, best-observed, or simply
relevant. Selected-reference comparison can compare against that marked run
without Scopecat needing special semantics for each label.

## Relationship To Prior Slices

This fixture reuses validated pressure without promoting shared architecture:

- selected export contributes explicit measurement selection;
- running inspection contributes declared preview metadata;
- parameter state contributes selected parameter-state context;
- setup binding contributes selected setup-binding and station-registry
  context.

The fixture uses named inputs because that vocabulary is useful, but it does
not earn a shared run-context framework.

## Remaining Risks

- the finding vocabulary may need more examples before it becomes a product
  warning taxonomy;
- reference selection UX is still undecided;
- quick plot preview comparison is future GUI pressure, not a plotting-quality
  contract;
- raw-data and fit-quality comparison remain separate future slices;
- user scripts or humans may still make higher-level judgments from Scopecat
  records, but that is outside this fixture;
- recipient-aware redaction remains broader than this fixture.

## Current Recommendation

Stop this slice at fixture validation unless a near-term task needs a
production-shaped summary candidate. Use the fixture as comparison pressure
when designing measurement run context, selected references, and future
review/report surfaces.

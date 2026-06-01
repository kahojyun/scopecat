# Measurement Context Route

## Status

Partially promoted engineering prototype.

The current live owner covers explicit context-link construction and resolved
context-link comparison:

- [`../../../../scopecat/measurement_context/README.md`](../../../../scopecat/measurement_context/README.md)
- [`../../../architecture/measurement-context/context-link-construction-decision.md`](../../../architecture/measurement-context/context-link-construction-decision.md)
- [`../../../architecture/measurement-context/resolved-context-link-comparison-decision.md`](../../../architecture/measurement-context/resolved-context-link-comparison-decision.md)

Artifact posture: `internal_validation_summary`.

This route note coordinates discovery evidence and live engineering posture. It
is not public documentation, a shared context schema, a relation graph, a
storage contract, a restore contract, or a GUI design.

## Promoted Boundaries

The first accepted engineering prototype summarizes explicit measurement
records, family-owned context record summaries, and resolved or missing
optional context links into local context-link review data.

It allows measurement records with zero context links, keeps linked context
reference-only, and treats missing optional context as review findings rather
than primary-data validity failures.

The comparison engineering prototype compares actual resolved
measurement-record context links between a current measurement record and a
user-selected reference measurement record.

The comparison output is local review data with objective changed,
same-observed, and missing optional-context findings. It does not compare
measurement intent selectors, primary data, fit quality, context payloads,
readiness, hardware runtime state, cause attribution, recursive relations,
context import, write-back, restore behavior, execution, or GUI behavior.

Neither promoted surface stores or mutates context links, defines a shared
context schema, or accepts a relation graph.

## Historical Evidence

- [`../../synthesis/measurement-context-backlog.md`](../../synthesis/measurement-context-backlog.md)
- [`../../slices/README.md`](../../slices/README.md)
- [`../../../../implementation_candidates/measurement_context_link/README.md`](../../../../implementation_candidates/measurement_context_link/README.md)
- [`../../../../implementation_candidates/resolved_context_link_comparison/README.md`](../../../../implementation_candidates/resolved_context_link_comparison/README.md)

## Still Candidate-Only

The broader measurement-context support backlog remains candidate-only:

- named run-start input sets;
- measurement context-link storage or mutation;
- supporting evidence references;
- artifact provenance and observation;
- post-run review bundles;
- context readiness projection.

## Reopen Triggers

Update this route and the promotion map when a branch changes any of these
boundaries:

- resolved-link comparison API or finding semantics;
- context-link construction, storage, or mutation behavior;
- payload reads, recursive traversal, context import, restore, or execution;
- readiness/run-blocking claims;
- selected-reference, prepared-run, or measurement-record consumption
  semantics;
- GUI/notebook review presentation.

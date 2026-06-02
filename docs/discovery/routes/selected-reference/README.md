# Selected Reference Route

## Status

Discovery route index; implementation candidate only.

This route groups selected-reference comparison evidence and current
implementation posture. The previous selected-reference context and
recorded-code comparison live module was withdrawn because it mechanically
promoted candidate summaries instead of owning a workflow-shaped comparison
step.

The route still does not accept raw-data comparison, fit-quality comparison,
setup truth, restore behavior, execution, cause attribution, GUI behavior, or a
shared context schema.

## Route Posture

Selected-reference comparison is currently validated as a side-effect-free
local review projection:

- reference selection starts from ordinary user marks on measurement records;
- current and reference measurement facts are paired by explicit IDs;
- declared preview metadata and named input snapshots can be compared as
  objective context;
- recorded code context can be compared through declared recorded-code facts;
- findings distinguish changed, missing, unverified, redacted, unlinked,
  same-observed, and not-compared scope;
- user scripts or humans remain responsible for interpretation.

## Current Evidence

| Surface | Owner |
| --- | --- |
| Problem framing and finding vocabulary. | [`../../problem-briefs/selected-reference-comparison.md`](../../problem-briefs/selected-reference-comparison.md) |
| Basic context and recorded-code validation result. | [`../../slices/selected-reference/selected-reference-comparison-validation-result.md`](../../slices/selected-reference/selected-reference-comparison-validation-result.md) |
| Historical implementation candidate. | [`../../../../implementation_candidates/selected_reference_comparison/README.md`](../../../../implementation_candidates/selected_reference_comparison/README.md) |

## Boundary

The validated candidate compares declared context facts only. It does not:

- read measurement payloads;
- compare fit quality;
- inspect Git state or source files;
- restore, import, or execute code;
- resolve dependency closure or runtime readiness;
- prove physical setup truth;
- score reference goodness;
- infer why a measurement changed.

## Next Useful Work

Prefer new slices only when they answer a concrete workflow question that
changes an authority boundary. High-value follow-ups are:

- promote resolved measurement-record context-link comparison as a separate
  measurement-context support surface;
- test GUI/notebook review presentation over comparison findings;
- validate quick preview/overlay consumption over compatible declared preview
  metadata;
- validate raw-data or fit-quality comparison separately from context
  comparison.

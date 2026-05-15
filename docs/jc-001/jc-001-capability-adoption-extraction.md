# JC-001 Design Pressure Adoption Extraction

## Status

Provisional first-wedge pressure only; later artifacts use it as input without
promoting a broader adoption plan or capability map.

## Purpose

Extract the design pressures touched by
[`jc-001-work-bundle-explanation-journey.md`](jc-001-work-bundle-explanation-journey.md)
and define the smallest product-value adoption step they suggest.

This note is scoped to `JC-001`. It does not define the full capability map,
ownership model, architecture contracts, subsystem specs, or implementation
plan.

## Extraction Rule

Start from the read journey, then preserve the missing-fact pressure that
explains why the read view is incomplete without turning those gaps into
write-side requirements.

```text
read need
  -> visible missing facts
  -> product-value adoption step
  -> later composition path
```

Do not infer that every missing fact requires managed execution, services,
databases, write-back, hardware control, or environment management. Some facts
can come from passive recording, explicit user selection, static inspection,
lightweight manifests, or export metadata.

## Design Pressure Touches

These labels preserve useful capability intent from earlier research without
accepting those labels as product surfaces, subsystem owners, or migration
routes.

| Design pressure | Why `JC-001` touches it | Status in this note |
| --- | --- | --- |
| Run and bundle evidence | The journey needs a stable work-bundle or run-like anchor, copied snapshots, generated sidecars, and artifact roles. | Provisional first-wedge pressure only. |
| Settings and context evidence | Settings and parameter-like files need source, role, freshness, conflict, snapshot, and variant treatment without write-back. | Provisional first-wedge pressure only. |
| Code and dependency provenance | Code-shaped evidence explains path selection, settings read, and sidecar derivation without managed execution. | Provisional first-wedge pressure only. |
| Setup and runtime boundary evidence | Setup and registry-like evidence appears as declared or observed context before device control. | Context-only pressure; no live runtime adoption yet. |
| Execution readiness evidence | Dependency and readiness pressure appears, but execution remains out of scope. | Diagnostic pressure only; defer runner adoption. |
| Conflict diagnostics | Conflict display is needed inside one bundle, but known-good comparison remains follow-on. | Limited diff pressure only; no comparator adoption yet. |

## Product-Value Adoption Steps

The deferred boundary is owned by
[`jc-001-passive-evidence-view-decision.md`](jc-001-passive-evidence-view-decision.md).

| Design pressure | Smallest useful product-value step | Read-side missing facts to keep visible | Later composition path |
| --- | --- | --- | --- |
| Run and bundle evidence | Open an existing work bundle and produce an artifact-role inventory anchored by a run-like or bundle identity. | Missing anchor, role, lifecycle, copied snapshot, generated sidecar, or included/excluded artifact explanation. | Later run records can link scan points, parameter snapshots, code references, execution records, and handoff packages. |
| Settings and context evidence | Show selected settings, copied snapshots, generated context, variants, conflicts, freshness, and unknown active state as evidence. | Missing selected source, selection reason, freshness, snapshot coverage, variant status, or context mismatch. | Later calibration workflows can propose updates, review diffs, and link accepted snapshots to runs. |
| Code and dependency provenance | Surface code-shaped evidence that explains settings path selection and derivation flow without executing it. | Missing entrypoint, code origin, settings path reference, dependency or lockfile clue, or sidecar generator reference. | Later managed execution can resolve exact code versions and execution records after safety boundaries exist. |
| Setup and runtime boundary evidence | Represent setup/registry-like context as declared or observed evidence with role and sharing boundary. | Missing setup source, verification status, physical-context freshness, or unsafe-to-verify label. | Later diagnostics and resource semantics can build on manifests after ADRs for device apply and leases. |
| Execution readiness evidence | Show readiness gaps and dependency-shaped clues as static evidence. | Missing dependency category, environment clue, expected output shape, or failure-policy hint. | Later runner records can capture logs, artifacts, status, and environment after control-PC safety decisions. |
| Conflict diagnostics | Explain conflicts between artifacts inside one bundle with layer-by-layer evidence. | Missing source, relation, affected fact, next-check wording, or reason a winner cannot be selected. | Later known-good comparison can compare bundle, setup, method, calibration, and analysis layers. |

## First Adoption Slice

The first useful slice is not "write a perfect run record." It is:

```text
existing bundle
  -> role inventory
  -> selected-context explanation
  -> code-shape provenance
  -> missing-fact gaps
  -> public-safe fixture evidence view
```

This slice can be useful even when the producer did not record everything. The
system should show what is observed, inferred, copied, generated, unchecked,
or missing.

## Missing Facts Worth Preserving

These are facts the read view may show as missing, inferred, copied,
generated, unchecked, or unsafe to verify. They are not required inputs and do
not define a future write-side API.

| Fact | Why it matters | First-slice handling |
| --- | --- | --- |
| Bundle or run-like anchor | Gives the explanation a stable entry point. | Represent, even if imported from existing files. |
| Artifact role | Separates anchor, selected context, generated sidecar, copied snapshot, variant, and unknown evidence. | Represent for included artifacts; represent backups through relation-level ambiguity. |
| Evidence handling | Prevents observed, inferred, generated, copied, unchecked, and unsafe evidence from looking equivalent. | Represent for artifacts and relations. |
| Selected settings source | Explains which settings appear selected without making them authoritative. | Represent as observed, inferred, or missing. |
| Snapshot relation | Explains why a copied settings file may differ from current settings. | Represent when snapshots are present. |
| Generated relation | Explains sidecars without claiming every sidecar is current. | Represent when sidecars are present. |
| Code reference | Explains path selection or derivation flow without execution. | Represent as lightweight evidence. |
| Sharing boundary | Keeps internal diagnostics and public exports separate. | Represent with fixture-safe labels. |
| Dependency/readiness hint | Shows execution risk before running code. | Include when visible. |
| Variant lineage | Preserves branch ambiguity. | Include one representative example. |

## Evidence View Ordering

For `JC-001`, layer the evidence view in this order:

1. Artifact-role inventory anchored by a bundle or run-like object.
2. Selected-context and snapshot explanation for settings-like files.
3. Generated-sidecar relation and completeness gaps.
4. Code-shape provenance for settings selection and derivation.
5. Sharing-boundary and redaction view.
6. Static readiness hints.
7. Follow-on known-good or scientific comparability only after this slice is
   validated.

This order keeps the first slice read-first while preserving missing-fact
pressure for future decisions.

## Migration-Wedge Candidate

Shape the first W4 wedge as:

```text
existing work bundle
  -> explainable context bundle
```

The user-visible outcome is an offline evidence view that explains selected
context, code-shaped provenance, generated and copied artifacts, variants,
ambiguity, and sharing boundaries without mutation.

The accepted decision owns the non-goals for this slice.

## Open Questions For W4/W6

- Which artifact-role vocabulary should become a stable domain concept.
- Whether selected context, generated relation, and copied snapshot should
  share one relation model or stay separate in the first implementation.
- How to express freshness without implying live truth.
- How to represent code references without accepting code identity ownership.
- Which sharing-boundary labels are needed before public docs or external
  support packages exist.
- Which static readiness hints are useful enough to include in the first wedge.

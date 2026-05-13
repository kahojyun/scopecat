# JC-001 Capability Adoption Extraction

## Status

Provisional first-wedge pressure only; later artifacts use it as input without
promoting a broader adoption plan.

## Purpose

Extract the capabilities touched by
[`jc-001-work-bundle-explanation-journey.md`](jc-001-work-bundle-explanation-journey.md)
and define the smallest standalone adoption step for each one.

This note is scoped to `JC-001`. It does not define the full capability map,
ownership model, architecture contracts, subsystem specs, or implementation
plan.

## Extraction Rule

Start from the read journey, then preserve the producer-fact pressure that
would make that read journey easier to explain later.

```text
read need
  -> recoverable producer facts
  -> standalone adoption step
  -> later composition path
```

Do not infer that every producer fact requires managed execution, services,
databases, write-back, hardware control, or environment management. Some facts
can come from passive recording, explicit user selection, static inspection,
lightweight manifests, or export metadata.

## Capability Touches

| Capability pressure | Why `JC-001` touches it | Status in this note |
| --- | --- | --- |
| Measurement History | The journey needs a stable work-bundle or run-like anchor, copied snapshots, generated sidecars, and artifact roles. | Provisional first-wedge pressure only. |
| Parameter Memory | Settings and parameter-like files need source, role, freshness, conflict, snapshot, and variant treatment without write-back. | Provisional first-wedge pressure only. |
| Code Asset Registry | Code-shaped evidence explains path selection, settings read, and sidecar derivation without managed execution. | Provisional first-wedge pressure only. |
| Instrument Runtime | Setup and registry-like evidence appears as declared or observed context before device control. | Context-only pressure; no live runtime adoption yet. |
| Managed Code Runner | Dependency and readiness pressure appears, but execution remains out of scope. | Diagnostic pressure only; defer runner adoption. |
| Comparability and conflict review | Conflict display is needed inside one bundle, but known-good comparison remains follow-on. | Limited diff pressure only; no comparator adoption yet. |

## Standalone Adoption Steps

The deferred boundary is owned by
[`jc-001-passive-evidence-view-decision.md`](jc-001-passive-evidence-view-decision.md).

| Capability | Smallest useful standalone adoption step | Recoverable producer facts | Later composition path |
| --- | --- | --- | --- |
| Measurement History | Open an existing work bundle and produce an artifact-role inventory anchored by a run-like or bundle identity. | A producer or importer can expose anchor identity, copied snapshots, generated sidecars, and artifact roles. | Later run records can link scan points, parameter snapshots, code references, execution records, and handoff packages. |
| Parameter Memory | Show selected settings, copied snapshots, generated context, variants, conflicts, freshness, and unknown active state as evidence. | A producer can record or expose selected settings source, snapshot relation, generated relation, and variant classification. | Later calibration workflows can propose updates, review diffs, and link accepted snapshots to runs. |
| Code Asset Registry | Surface code-shaped evidence that explains settings path selection and derivation flow without executing it. | A producer can expose entrypoint-like evidence, settings path references, data path references, and sidecar generator references. | Later managed execution can resolve exact code versions and execution records after safety boundaries exist. |
| Instrument Runtime | Represent setup/registry-like context as declared or observed evidence with role and sharing boundary. | A producer can expose setup context as evidence without proving live device state. | Later diagnostics and resource semantics can build on manifests after ADRs for device apply and leases. |
| Managed Code Runner | Show readiness gaps and dependency-shaped clues as static evidence. | A producer can expose dependency categories or environment hints without installing or running anything. | Later runner records can capture logs, artifacts, status, and environment after control-PC safety decisions. |
| Comparability and conflict review | Explain conflicts between artifacts inside one bundle with layer-by-layer evidence. | A producer can preserve enough source and relation metadata for later conflict display. | Later known-good comparison can compare bundle, setup, method, calibration, and analysis layers. |

## First Adoption Slice

The first useful slice is not "write a perfect run record." It is:

```text
existing bundle
  -> role inventory
  -> selected-context explanation
  -> code-shape provenance
  -> producer-fact gaps
  -> public-safe fixture evidence view
```

This slice can be useful even when the producer did not record everything. The
system should show what is observed, inferred, copied, generated, unchecked,
or missing.

## Minimal Producer Facts

These are the facts `JC-001` suggests producers should eventually record or
make recoverable:

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

## Capability Ordering

For `JC-001`, layer the evidence view in this order:

1. Artifact-role inventory anchored by a bundle or run-like object.
2. Selected-context and snapshot explanation for settings-like files.
3. Generated-sidecar relation and completeness gaps.
4. Code-shape provenance for settings selection and derivation.
5. Sharing-boundary and redaction view.
6. Static readiness hints.
7. Follow-on known-good or scientific comparability only after this slice is
   validated.

This order keeps the first slice read-first while preserving producer-fact
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

## Promotion Chain

See [`README.md`](README.md) for the current reading order and promotion chain.

# JC-001 Design Pressure

## Status

Design memory only. This note preserves pressure discovered through `JC-001`
without accepting a capability map, subsystem owner, write-side API, or future
product route.

## Purpose

Keep the design intent that remains useful after the accepted passive
evidence-view slice, especially the missing facts that later journeys may need
to record, validate, or intentionally leave as user-owned risk.

## Pressure Preserved

| Pressure | What `JC-001` proved | Later design implication |
| --- | --- | --- |
| Run or bundle anchor | A passive report needs one bounded object to explain. | Durable recording and handoff journeys should preserve stable anchors, but `JC-001` does not decide the storage model. |
| Artifact roles | Files need user-facing roles before their contents are interpreted. | Later import/export, handoff, and lineage work should keep role explicit instead of relying on extensions or paths. |
| Selected context | Settings-like files can appear selected without being authoritative truth. | Future producer-side features may record selection reason and freshness, but passive explanation must still handle absence. |
| Generated and copied artifacts | Sidecars and snapshots can explain workflow history while being stale or partial. | Later lineage work should preserve source relation and invalidation evidence when available. |
| Code-shaped evidence | Static code clues help explain selection and derivation without execution. | Code portability or runner work should build on explicit code identity only after separate safety decisions. |
| Setup evidence | Registry or setup-like files are useful context but not proof of physical truth. | Setup, apply, leases, and hardware verification require later ADRs and runtime boundaries. |
| Static readiness | Dependency and expected-output clues are useful before execution. | Readiness can remain diagnostic until a managed runner or runtime handoff is accepted. |
| Sharing boundary | Public output needs stable public identities and redaction behavior. | Public/export/support flows need explicit recipient-aware policy before broader sharing claims. |

## Missing Facts To Preserve

These facts are reportable gaps, not required inputs:

- preferred bundle or run anchor;
- artifact role;
- evidence handling: observed, inferred, generated, copied, user-declared,
  unchecked, unsafe-to-inspect, or missing;
- selected settings source and selection reason;
- source timestamp or freshness marker;
- generated artifact source and invalidation rule;
- copied snapshot source and coverage;
- code origin or immutable code reference;
- dependency or readiness clue;
- sharing boundary for sensitive source details.

## Design Rule

Do not turn a missing fact into mandatory producer scope by default. Later
journeys should decide whether the fact is best supplied by explicit recording,
user selection, static inspection, export metadata, or no product ownership.

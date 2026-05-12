# JC-001 Work Bundle Explanation Journey

## Status

Promoted through capability extraction and the accepted passive evidence-view
decision.

## Purpose

Define the first W2 current-state and future-state journey for `JC-001`:
explain an existing run or work bundle with selected context, code, and
artifacts.

This journey uses the fixture and sharing boundary selected in
[`jc-001-journey-selection-note.md`](jc-001-journey-selection-note.md). The
accepted implementation boundary lives in
[`jc-001-passive-evidence-view-decision.md`](jc-001-passive-evidence-view-decision.md).

## Job To Be Done

When I need to understand or reuse an inherited experiment work bundle, help me
see which configuration, settings, generated sidecars, copied run snapshots,
code references, and variants appear relevant or conflicting, so I can decide
what must be checked before analysis, handoff, or another run.

## Fixture Scope

The journey starts from a small synthetic configuration-bundle fixture:

```text
compact root config files
  -> broader runtime-selected setting bundle
  -> generated or copied sidecars
  -> variant and backup evidence
```

The fixture is intentionally ambiguous. The root files look like compact
anchors. The selected settings look closer to the runtime path. Generated
sidecars and copied snapshots may carry useful context, but they may not match
the current selected settings. Variants and backups may look relevant without
proving active state.

Scopecat must explain this evidence without declaring a hidden source of truth.

## Producer-Side Trace

Although the first journey is read-first, the bundle did not appear from
nowhere. The fixture implies a minimal producer-side path:

```text
ordinary script or notebook chooses settings path
  -> settings are read for a run-like action
  -> optional sidecars are derived from selected settings
  -> a run-bound snapshot may be copied beside data
  -> variants and backups accumulate as users adapt the workflow
  -> later user reopens the bundle and tries to recover intent
```

This trace is descriptive, not accepted write scope. It explains which facts
must be discoverable later, without requiring Scopecat to control execution,
own settings, mutate calibration, or manage environments.

## Producer-Fact Implications

The read journey identifies producer facts that future write decisions may need
to preserve. It does not accept a write platform.

| Read need | Future producer fact | Not accepted yet |
| --- | --- | --- |
| Explain which settings were selected. | Expose or discover the selected settings source, its role, and whether selection is observed, inferred, copied, or user-declared. | Scopecat-owned configuration truth or automatic settings write-back. |
| Explain generated sidecars. | Represent or infer `produced-by` relations from selected settings to derived sidecars, with freshness and unchecked labels. | Automatic sidecar generation as a required runtime behavior. |
| Explain copied run snapshots. | Preserve copied-from or snapshot-of relations, including when the copy may differ from current settings. | Durable transaction semantics, resumability, or old-history import. |
| Explain code-shaped provenance. | Capture enough code reference to identify path selection, entrypoint-like evidence, and derivation flow. | Managed execution, notebook-state capture, package registry, or remote runner scope. |
| Explain variants and backups. | Classify variants separately from selected context and expose unknown active state. | Automatic precedence rules, rollback, restore, or deployment management. |
| Share the explanation safely. | Mark fields and artifacts by sharing boundary and redact public/exported views. | A general support-ticketing product or full collaboration workflow. |

These facts can be supplied by passive recording, explicit user selection,
static inspection, or lightweight export metadata. The journey does not decide
which mechanism is best.

## Actors

| Role hat | Need in this journey |
| --- | --- |
| Operator | Understand whether a bundle is safe to inspect or reuse without touching hardware. |
| Analyst | Recover which context and sidecars explain a run-like artifact or result. |
| Method author | See which code-shape evidence selected or derived settings. |
| Configuration reviewer | Identify conflicts, freshness gaps, and unsafe assumptions before mutation or reuse. |
| Recipient | Receive a public-safe explanation without private lab details; internal-safe view differences remain follow-on validation. |

## Entry Conditions

- A user has an inherited or reopened work bundle.
- The bundle includes multiple plausible context sources, not one clean project
  manifest.
- The user wants explanation and triage before analysis, handoff, or another
  run.
- The workflow is offline: no code execution, notebook execution, hardware
  access, driver communication, package installation, or environment mutation.

## Current-State Journey

| Step | Role hat | Current user action | What makes it hard | Evidence pressure |
| --- | --- | --- | --- | --- |
| 1 | Operator or analyst | Open the bundle and look for an obvious entry point. | Compact root config files look important, but do not prove runtime selection. | `PN-001`, `PN-002` |
| 2 | Configuration reviewer | Compare root config with broader settings. | Related files overlap in object names and concepts but conflict in breadth, naming, and values. | `PN-002`, `PN-021` |
| 3 | Method author | Inspect code-shaped clues to infer which settings may be read or derived. | The useful code clue is a path-selection and settings-derivation flow, but executing it would cross safety boundaries. | `PN-006`, `PN-005`, `PN-022` |
| 4 | Analyst | Look for generated sidecars and copied snapshots near run-like artifacts. | Sidecars may be stale, generated from a different settings state, or copied after the primary artifact. | `PN-001`, `PN-002`, `PN-006` |
| 5 | Configuration reviewer | Notice variants and backups that appear related. | Variant names imply history or branch intent, but static files do not prove active state or precedence. | `PN-002`, `PN-020`, `PN-021` |
| 6 | Analyst or recipient | Prepare to continue analysis or ask for help. | The useful diagnostic context is scattered and may include details unsafe for public or external sharing. | `PN-007`, `PN-023` |

## Current-State Outcome

The user can manually collect clues, but the result is fragile:

- artifact roles are implicit in filenames and local conventions;
- root config, selected settings, sidecars, snapshots, and variants are not
  clearly separated;
- code provenance is mixed with executable hardware-facing code;
- conflicts are easy to miss or overinterpret;
- sharing boundaries are unclear;
- the user may either trust too much or give up and copy the whole bundle.

## Future-State Journey

| Step | Role hat | Scopecat behavior | User decision enabled |
| --- | --- | --- | --- |
| 1 | Operator or analyst | Opens the bundle in offline explanation mode and identifies anchor artifacts, selected-context candidates, generated sidecars, copied snapshots, variants, and unknowns. | Decide where to start reading without treating any file as authoritative truth. |
| 2 | Configuration reviewer | Shows root config and runtime-selected settings as related but conflicting evidence, with role, status, provenance, and evidence-handling labels. | Decide which conflicts need human review before reuse. |
| 3 | Method author | Summarizes non-executable code-shape evidence: path selection, settings read, optional sidecar generation, and run-bound snapshot pattern. | Decide whether the bundle has enough code provenance to explain settings flow. |
| 4 | Analyst | Groups generated sidecars and copied snapshots with the settings evidence they appear derived from or attached to, while marking stale or unchecked relations. | Decide whether the run-like artifact is explainable enough for analysis. |
| 5 | Configuration reviewer | Lists variant and backup evidence separately from selected context and explains why active state is unknown. | Decide which variant, if any, needs external confirmation. |
| 6 | Recipient | Produces a sharing-safe explanation view with sensitive fields categorized or replaced by public labels. | Decide what can be shared for handoff or support. |

## Future-State Output

The first useful output is an evidence view for one bundle:

- anchor artifacts;
- selected-context candidates;
- generated, copied, variant, unknown, fixture-authored evidence, and backup
  relation ambiguity;
- observed, inferred, generated, copied, unchecked, and unsafe-to-inspect
  handling labels;
- conflict notes between compact root config and runtime-selected settings;
- sidecar completeness and freshness gaps;
- code-shape provenance without execution;
- sharing-boundary labels;
- next checks the user should perform before analysis, handoff, or reuse.

The output is not a migration, repair, execution package, rollback plan, or
scientific-equivalence judgment.

## Acceptance Checks

| Check | Must be true |
| --- | --- |
| `PN-002` selected context | The journey shows why root config, runtime settings, sidecars, snapshots, and variants are all context evidence, and why none is automatically truth. |
| `PN-006` code provenance | The journey explains settings selection and derivation from code-shape evidence without executing code or capturing notebook state. |
| `PN-005` readiness | The journey surfaces dependency and safety boundaries before any execution or hardware contact. |
| `PN-001` explainability | The journey makes clear that a compact config or run-like snapshot alone is insufficient without companion artifacts. |
| `PN-020` truth drift | The journey records source, role, freshness, and ambiguity instead of creating a silent second truth store. |
| `PN-021` false confidence | Missing, stale, conflicting, unchecked, and generated evidence stays visible; no numeric confidence score is required. |
| `PN-022` control-PC safety | The journey remains offline and read-only. |
| `PN-023` sharing boundary | The journey distinguishes internal diagnostic detail from public-safe or external-support output. |
| `PN-007` portability | Local and machine-specific coupling is represented as redaction-sensitive evidence, not public fixture content. |
| `PN-016` low ceremony | A user can start from ordinary files and code-shaped evidence without adopting a managed framework. |

## W3 Handoff Notes

| Check | Must be true |
| --- | --- |
| Read needs imply producer-fact pressure | Capability extraction must identify which facts need to exist at bundle-production time or be recoverable later. |
| Mechanism remains open | The journey must not assume those facts come from a managed runner, database, service, notebook capture, or control framework. |
| Failure stays visible | If a producer did not record enough information, the future-state output must show missing or inferred evidence rather than fabricating certainty. |
| Low ceremony survives | Existing ordinary scripts can produce or expose useful evidence without becoming full Scopecat applications. |

## Explicit Non-Goals

This journey does not accept:

- code execution, notebook execution, driver communication, service startup, or
  hardware contact;
- write-back to settings, calibration mutation, rollback, restore, or automatic
  repair;
- package installation, environment solving, cloud login, background agents, or
  mandatory network services;
- old-history import, Data Vault emulation, generic file organization, or full
  ELN/report-generator scope;
- authoritative ownership of parameters, setup state, physical truth, notebook
  state, code execution, or arbitrary legacy-file truth;
- scientific comparability scoring or known-good reference comparison.

## Capability Pressure Promoted

These were extraction prompts for W3, not accepted capability documents. They
are promoted into
[`jc-001-capability-adoption-extraction.md`](jc-001-capability-adoption-extraction.md)
and later narrowed by
[`jc-001-passive-evidence-view-capability-ownership.md`](jc-001-passive-evidence-view-capability-ownership.md).

| Capability pressure | Why the journey touches it |
| --- | --- |
| Measurement History | The bundle needs stable anchors, copied snapshots, sidecars, and run-like artifact explanation. |
| Parameter Memory | Settings and parameter-like files need role, freshness, conflict, and snapshot treatment without write-back. |
| Code Asset Registry | Code-shaped evidence explains path selection and derivation without managed execution. |
| Instrument Runtime | Setup and registry-like evidence appears, but only as declared or observed context before device control. |
| Managed Code Runner | Dependency and readiness pressure appears, but execution remains out of scope. |
| Comparability and known-good diff | Conflict display is needed, but known-good comparison and equivalence judgment remain follow-on scope. |

## Remaining Handoff Questions

- Which role names should become durable user-facing terms rather than
  internal evidence labels?
- Which producer facts need explicit future API support, and which can remain
  recoverable by static inspection or user selection?
- Which freshness labels are useful beyond observed, generated, copied,
  unchecked, and user-declared relation evidence?
- How should a public-safe export describe redacted fields while preserving
  diagnostic value for handoff?
- When does code-shape evidence need durable code identity rather than
  text-only references?

## Promotion Chain

See [`README.md`](README.md) for the current reading order and promotion chain.

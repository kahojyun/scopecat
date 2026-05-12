# JC-001 Work Bundle Explanation Journey

## Status

Ready for capability and adoption-ladder extraction.

## Purpose

Define the first W2 current-state and future-state journey for `JC-001`:
explain an existing run or work bundle with selected context, code, and
artifacts.

This journey is public-safe and fixture-based. It uses the boundary selected in
[`jc-001-journey-selection-note.md`](jc-001-journey-selection-note.md) and does
not promote implementation scope, architecture contracts, subsystem specs, or
live experiment control.

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

## Actors

| Role hat | Need in this journey |
| --- | --- |
| Operator | Understand whether a bundle is safe to inspect or reuse without touching hardware. |
| Analyst | Recover which context and sidecars explain a run-like artifact or result. |
| Method author | See which code-shape evidence selected or derived settings. |
| Configuration reviewer | Identify conflicts, freshness gaps, and unsafe assumptions before mutation or reuse. |
| Recipient | Receive a public-safe or internal-safe explanation without private lab details. |

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

| Step | Role hat | Scopecat behavior | User decision enabled | Boundary |
| --- | --- | --- | --- | --- |
| 1 | Operator or analyst | Opens the bundle in offline explanation mode and identifies anchor artifacts, selected-context candidates, generated sidecars, copied snapshots, variants, and unknowns. | Decide where to start reading without treating any file as authoritative truth. | No execution or mutation. |
| 2 | Configuration reviewer | Shows root config and runtime-selected settings as related but conflicting evidence, with role, status, provenance, and evidence-handling labels. | Decide which conflicts need human review before reuse. | No hidden source-of-truth claim. |
| 3 | Method author | Summarizes non-executable code-shape evidence: path selection, settings read, optional sidecar generation, and run-bound snapshot pattern. | Decide whether the bundle has enough code provenance to explain settings flow. | No managed execution or notebook-state capture. |
| 4 | Analyst | Groups generated sidecars and copied snapshots with the settings evidence they appear derived from or attached to, while marking stale or unchecked relations. | Decide whether the run-like artifact is explainable enough for analysis. | No automatic completeness proof. |
| 5 | Configuration reviewer | Lists variant and backup evidence separately from selected context and explains why active state is unknown. | Decide which variant, if any, needs external confirmation. | No rollback, restore, or precedence inference. |
| 6 | Recipient | Produces an internal-safe or public-safe explanation view with sensitive fields redacted or categorized. | Decide what can be shared for handoff or support. | No raw private context in public output. |

## Future-State Output

The first useful output is an evidence view for one bundle:

- anchor artifacts;
- selected-context candidates;
- generated, copied, backup, variant, unknown, and fixture-authored roles;
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

## Capability Pressure For Next Step

These are extraction prompts for W3, not accepted capability documents:

| Capability pressure | Why the journey touches it |
| --- | --- |
| Measurement History | The bundle needs stable anchors, copied snapshots, sidecars, and run-like artifact explanation. |
| Parameter Memory | Settings and parameter-like files need role, freshness, conflict, and snapshot treatment without write-back. |
| Code Asset Registry | Code-shaped evidence explains path selection and derivation without managed execution. |
| Instrument Runtime | Setup and registry-like evidence appears, but only as declared or observed context before device control. |
| Managed Code Runner | Dependency and readiness pressure appears, but execution remains out of scope. |
| Comparability and known-good diff | Conflict display is needed, but known-good comparison and equivalence judgment remain follow-on scope. |

## Open Questions

- What is the minimum role vocabulary for artifacts: anchor, selected context,
  generated sidecar, copied snapshot, variant, backup, unknown, and
  fixture-authored may be enough for the first slice.
- Which freshness labels are needed before implementation: observed timestamp,
  generated relation, copied relation, unchecked relation, or user-declared
  relation.
- How should a public-safe export describe redacted fields while preserving
  enough diagnostic value for handoff.
- Which code-shape evidence should become a durable concept: entrypoint,
  settings path, data path, sidecar generator, or run snapshot relation.
- Whether the next W3 artifact should be a small adoption ladder note or a
  capability-pressure note for only the capabilities touched here.

## Next Step

Extract the capabilities touched by this journey and define their smallest
standalone adoption steps. Keep the extraction tied to this offline bundle
explanation journey; do not create subsystem specs or implementation plans yet.

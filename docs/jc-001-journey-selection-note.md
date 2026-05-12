# JC-001 Journey Selection Note

## Status

Ready for first W2 journey drafting.

## Purpose

Select the first W2 journey candidate and define the public-safe fixture
boundary before writing current-state and future-state journey prose.

This note promotes only the fixture-selection decision. It is not a journey
document, capability map, architecture contract, subsystem spec, or
implementation plan.

## Selected Candidate

`JC-001`: explain an existing run or work bundle with selected context, code,
and artifacts.

This remains the strongest first journey because the selected fixture exercises
the main W2 acceptance pressure without requiring managed execution, device
control, write-back, environment management, old-history import, rollback, or
claims that Scopecat owns lab truth.

## Fixture Boundary

Use a grounded synthetic configuration-bundle fixture derived from internal
source-map work. The synthetic fixture is intentionally small and redacted. It
contains:

- compact root configuration seed files;
- broader runtime-selected setting files;
- generated sidecar placeholders;
- a copied run-bound settings snapshot;
- a variant manifest;
- non-executable code-shape evidence.

The fixture deliberately preserves a layered ambiguity:

```text
compact root config files
  -> broader runtime-selected setting bundle
  -> generated or copied sidecars
  -> variant and backup evidence
```

The journey should not resolve this ambiguity by declaring one artifact as the
authoritative truth. It should show source, freshness, role, provenance,
evidence handling, and uncertainty clearly enough that a user can decide what
needs checking before reuse, handoff, or analysis.

## Acceptance Pressure

| Pressure | How the fixture exercises it |
| --- | --- |
| `PN-002` | Selected context is ambiguous across root config, runtime settings, generated sidecars, copied snapshots, and variants. |
| `PN-006` | Code-shape evidence explains which settings are read or derived without accepting managed execution or notebook-state capture. |
| `PN-005` | Readiness evidence appears before hardware execution: selected settings, optional sidecars, copied snapshots, and dependency-shaped code references. |
| `PN-001` | A compact config or run-bound snapshot alone cannot explain the work bundle without companion settings, generated artifacts, and provenance notes. |

## Guardrails

The first W2 journey must:

- keep fixture contents public-safe and role-based;
- treat configuration, setting, sidecar, and variant files as evidence, not
  authoritative truth;
- distinguish observed, inferred, generated, copied, and fixture-authored
  evidence;
- expose missing and conflicting evidence instead of collapsing it into a
  numeric trust score;
- preserve recipient-aware sharing boundaries.

The first W2 journey must not:

- execute code, notebooks, drivers, setup scripts, services, or hardware
  routines;
- require managed execution, live device control, old-history import,
  write-back, rollback, package installation, environment mutation, background
  services, cloud login, or automatic repair;
- claim Scopecat owns parameters, setup state, notebook state, code execution,
  physical truth, or arbitrary legacy-file truth;
- expand into a full ELN, report generator, file organizer, universal setup
  schema, deployment manager, or measurement-framework replacement.

## JTBD Conversion

When I need to understand or reuse an inherited experiment work bundle, help me
see which configuration, settings, generated sidecars, copied run snapshots,
code references, and variants appear relevant or conflicting, so I can decide
what must be checked before analysis, handoff, or another run.

## Current-State Journey Seed

The current-state journey should start from an inherited or reopened work
bundle where a user can see several plausible sources of context:

- a compact root configuration seed;
- a broader selected settings directory;
- generated sidecars that may or may not match the current settings;
- a copied settings snapshot attached to a run-like artifact;
- variants and backups that look related but are not obviously active;
- code-shape evidence that indicates how settings may be selected or derived.

The user currently has to inspect filenames, local conventions, copied files,
and code references manually. The journey should keep that manual recovery
visible while staying narrow enough to avoid device control or execution scope.

## Future-State Journey Seed

The future-state journey should show Scopecat opening the same work bundle and
presenting:

- anchor artifacts and selected-context candidates;
- generated, copied, backup, variant, and unknown artifact roles;
- evidence handling labels such as observed, inferred, generated, copied, and
  unchecked;
- conflicts between compact root configuration and runtime-selected settings;
- sidecar completeness and provenance gaps;
- public-safe sharing boundaries and redaction-sensitive fields;
- next checks the user should perform before reuse or handoff.

The output should be an explainable evidence view, not an automatic repair,
truth-store migration, or execution plan.

## Rejected Alternatives For First W2

`JC-009` remains a useful comparison and diagnostic alternative, but this
fixture does not require known-good comparison, rollback evidence, or
control-PC recovery scope.

`JC-010` remains a useful scientific-comparability alternative, but this
fixture should not score scientific equivalence or compare results across
screening systems.

Analysis-lineage and handoff fixtures remain good follow-on candidates after
the first bundle-explanation journey establishes artifact identity, selected
context, provenance, ambiguity, and sharing boundaries.

## Next Step

Write the selected journey in current-state and future-state form using this
fixture boundary. Keep the full workflow spine visible, but make the first
future slice an offline explanation and ambiguity review of an existing bundle.

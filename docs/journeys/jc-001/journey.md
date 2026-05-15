# JC-001 Work Bundle Explanation Journey

## Status

Accepted journey context for the passive evidence-view decision.

## Purpose

Explain the user need behind `JC-001`: an experiment user inherits or reopens
an existing work bundle and needs to understand which files, settings, code
clues, generated artifacts, snapshots, and variants appear relevant before
analysis, handoff, or reuse.

The accepted implementation boundary lives in
[`decisions/passive-evidence-view.md`](decisions/passive-evidence-view.md).

## Job To Be Done

When I need to understand or reuse an inherited experiment work bundle, help me
see which configuration, settings, generated sidecars, copied run snapshots,
code references, and variants appear relevant or conflicting, so I can decide
what must be checked before analysis, handoff, or another run.

## Current-State Pain

The source workflow is file-shaped rather than concept-shaped:

- compact root config files look like anchors but may not be the runtime
  selected context;
- runtime-selected settings may live deeper in the bundle;
- generated sidecars and copied snapshots may preserve useful context but may
  be stale or partial;
- variants and backups preserve history but do not establish precedence;
- code clues can explain selection or derivation, but executing inherited code
  is unsafe as a first step;
- local paths, labels, and bundle details may be sensitive outside the lab.

Users can often reopen a data object or find a folder, but still cannot explain
which companion artifacts matter or which facts are missing.

## Future-State Outcome

Scopecat reads a bounded existing bundle and produces a passive evidence view
that shows:

- artifact roles;
- selected-context candidates;
- generated and copied relations;
- code-shaped evidence without execution;
- variant and backup ambiguity;
- conflicts and missing facts;
- sharing and redaction handling;
- next checks before analysis, handoff, or reuse.

The view preserves ambiguity. It must not choose authoritative settings,
declare physical setup truth, execute code, repair files, or hide uncertainty
behind a numeric trust score.

## Fixture Shape

The accepted fixture family starts from:

```text
compact root config files
  -> broader runtime-selected setting bundle
  -> generated or copied sidecars
  -> variant and backup evidence
  -> non-executed code-shaped clues
```

This shape intentionally stresses selected-context ambiguity, generated/copy
relations, stale evidence, role labeling, and public-safe reporting.

## Acceptance Checks

The journey-level outcome is satisfied when a fixture-scale evidence view can:

- inventory all listed artifacts and assign explicit roles;
- show selected-context, generated, copied, code-reference, variant, backup,
  conflict, missing-fact, and redaction relations;
- preserve root/selected-context drift and snapshot ambiguity;
- represent setup-like files as declared or observed evidence only;
- expose missing selected source, generated source, snapshot coverage, code
  identity, and sharing-boundary facts;
- run without code execution, notebook execution, dependency installation,
  hardware contact, file mutation, or source repair.

Prototype-specific checks live in
[`prototypes/passive-evidence-view.md`](prototypes/passive-evidence-view.md).

## Non-Goals

This journey does not accept managed execution, old-history import, Data Vault
emulation, general file organization, full ELN/report generation, write-back,
rollback, environment solving, package installation, notebook-state capture,
hardware control, known-good comparison, scientific equivalence scoring, or
authority over parameters, setup state, physical truth, notebook state, code
execution, or arbitrary legacy-file truth.

## Follow-On Design Pressure

The journey preserves design pressure for:

- stable run or bundle anchors;
- artifact role and relation vocabulary;
- selected-context freshness and selection reason;
- generated and copied artifact lineage;
- code identity beyond text-only evidence;
- setup evidence that stays separate from physical truth;
- static readiness before execution;
- recipient-aware sharing boundaries.

Those pressures are recorded in [`design-pressure.md`](design-pressure.md).
They are not accepted producer requirements.

# JC-002 Handoff Snapshot Definition

## Status

Draft concept definition for `JC-002`. This document defines the current
product boundary for a handoff snapshot, not a manifest schema, reader API,
storage model, export format, UI spec, or validation result.

## Definition

A handoff snapshot is an immutable, portable, pre-analysis package containing
selected experiment data plus enough context to read, plot, and explain the
data on another computer.

It is created after one or more runs have been selected on an
experiment-control computer. It is consumed on a personal analysis computer by
user-owned analysis code or tools. Scopecat does not manage execution of that
analysis code in this slice.

```text
experiment-control computer
  -> user selects runs or datasets
  -> Scopecat packages already-known artifacts and context
  -> analysis computer
  -> user reads and analyzes snapshot
  -> derived figures, PDFs, slides, and fit results are produced separately
```

## Expected Consumer Surfaces

The intended product direction includes a purely local offline GUI and a Python
reader API for consuming snapshots on an analysis computer.

At this design stage, those surfaces are validation targets, not contracts.
`JC-002` may require a fixture to prove that a user can open a copied snapshot,
inspect metadata and warnings in a local GUI-like view, and load data through a
Python reader-like interface. It should not yet define final GUI behavior,
reader API signatures, package layout, or storage format.

The first useful consumer smoke test is:

```text
copy snapshot to a path unrelated to the control computer
  -> open locally without network, cloud login, or control-PC access
  -> list selected runs and warnings
  -> load one run with data, axes, units, labels, and required sidecars
  -> load the selected group with condition labels and per-run context
  -> make a basic single-run plot and group-level sanity plot
```

## Export Is Not Derivation

Creating a handoff snapshot is a packaging and manifesting operation. It does
not create new derived artifacts from source data.

At export time, Scopecat may package only artifacts and context that are
already known to the system or already attached by the user to the selected
runs. If a useful CSV, NPY, PNG, PDF, fit table, or report does not already
exist as a recorded artifact with an explicit role, handoff export should not
generate it.

New derived artifacts belong to a separate analysis or derived-record
workflow. Those later outputs may link back to the snapshot, but they do not
change what the original snapshot meant.

## Artifact Inclusion

Snapshot inclusion is role-based, not file-extension-based.

| Role | Default handling |
| --- | --- |
| primary_data | Include by default. |
| required_read_sidecar | Include by default when needed to open or interpret primary data. |
| handoff_context | Include by default when attached to the selected runs or snapshot. |
| calibration_or_correction_reference | Include as a reference by default; copy only when already attached or explicitly selected. |
| user_attached_derived_input | Show as an explicit export decision; include when the user has attached it for handoff or selected it during review. |
| analysis_output | Exclude by default; it belongs to derived analysis records. |
| report_artifact | Exclude by default; it belongs to derived analysis or report lineage. |
| internal_verification_reference | Include as a reference only by default; copy with an advanced internal-verification option. |
| unknown | Do not silently include. Either exclude with a warning or require explicit user selection. |

For example, an `.npy` file can be primary data, a required read sidecar, a
user-attached derived input, or an analysis output. Its role decides whether it
belongs in the snapshot.

## Default Include

The snapshot may include:

- selected run or dataset source identity;
- selected-run group identity, order, and labels when multiple runs are
  selected;
- primary data needed for analysis;
- read sidecars required to open the data;
- axis names, units, shapes, and value labels;
- measurement name, run label, timestamp, and source computer or station;
- sample, device, chip, or measurement-object labels when available;
- important swept and fixed parameter summaries;
- user-provided purpose, note, or selected reason;
- calibration, correction, or companion-artifact references when relevant;
- original source path evidence and stable IDs;
- context warnings for missing, unknown, ambiguous, or redacted fields.

## Source Identity Minimum

Each snapshot should preserve a concept-level identity bundle. This is not a
manifest schema, but the first fixture should exercise these facts:

- snapshot ID and creation time;
- producer or exporter version when known;
- source system type or name when known;
- control computer or station identity, with status such as provided,
  unknown, or redacted;
- source run or dataset IDs;
- original path evidence, treated as provenance rather than a portable read
  path;
- acquisition timestamp and measurement label;
- selected-run group membership, order, and group label when exporting more
  than one run;
- artifact role and source relation for each included artifact;
- size or checksum evidence sufficient to detect silent drift at fixture
  scale.

## Multi-Run Group Semantics

When multiple runs are selected, the snapshot should preserve both per-run
context and group-level context.

Group-level context may include:

- group title or selected reason;
- run order;
- condition labels such as baseline, control, sample, before, after, repeat, or
  excluded;
- shared context fields and per-run overrides;
- quality flags or exclusion notes;
- missing-context summaries across the group.

These are low-ceremony labels, not a scientific-comparison model. `JC-002`
does not decide whether runs are scientifically comparable.

## Default Exclude

The first snapshot definition excludes:

- generated PDFs, plots, decks, and reports;
- processed publication arrays;
- fit-result tables and interpreted claims;
- notebook output state;
- managed analysis environments;
- managed execution of user analysis scripts;
- active setup, parameter, configuration, or execution-state import;
- complete work-bundle export/import.

Those outputs can become later append-only derived analysis records linked back
to the snapshot. They must not mutate source data, configuration, setup,
parameter, or execution-state truth.

## Advanced Options

Advanced export options may broaden what is copied, but they should not change
the default handoff boundary or generate new artifacts. Candidate options
include:

- copy user-attached derived inputs;
- copy selected calibration or correction artifacts that are already recorded;
- copy selected notebooks or scripts attached by the user as handoff context;
- copy internal verification references instead of keeping references only;
- include full-fidelity local source path evidence for internal use;
- apply an external or public-safe redaction profile.

These are selection and packaging choices over known artifacts, not analysis
steps.

Advanced options should be off by default. Each copied advanced artifact should
have a role, source relation, and warning text when its sharing or execution
risk is non-obvious. Notebooks and scripts may be copied only as inert files in
this slice; snapshot export must never run them. Unknown-role files are
excluded unless the user explicitly selects and classifies them.

## Control-PC Safety Invariants

Snapshot export must be safe for conservative experiment-control computers:

- read-only against source runs and control state;
- no instrument, registry, setup, parameter, or live-control writes;
- no execution of notebooks, scripts, analysis code, setup code, drivers, or
  fixture code;
- no generated plots, arrays, fits, reports, or decks during export;
- copy only selected runs, required sidecars, and explicitly role-labeled
  attachments;
- preserve source records unchanged;
- show estimated size and destination before large copies when a UI exists.

## Context Tiers

Use tiers to separate what must travel with the data from what is useful only
for deeper investigation.

| Tier | Purpose | Typical fields | Handling |
| --- | --- | --- | --- |
| Tier 1: read and plot | Make the selected data openable and plottable on another computer. | Source ID, primary data, required sidecars, axis names, units, shape, timestamp, measurement label. | Required manifest slots. Missing values should become explicit warnings. |
| Tier 2: meeting explanation | Help a user explain the measurement in lab discussion, slides, or ordinary handoff. | Sample/device label, measurement-object label, purpose note, selected reason, important parameters, condition labels, run order, quality flags, exclusion notes, relevant calibration/correction references. | Required slots for a meeting-useful snapshot, but user input may be explicitly not provided. |
| Tier 3: internal verification | Support internal debugging, audit, or full context checking. | Full config references, registry or wiring references, related calibration runs, code references, previous-good comparison links, operator notes. | Optional references by default; often internal-only and unsuitable for external sharing. |

Tier 3 should not block snapshot creation. In many lab workflows it is enough
for Tier 3 to point back to the original control computer, source bundle, or
internal record location.

## Required Slots Versus Required Values

For Tier 1 and Tier 2, "required" means the snapshot contract has a required
slot. It does not mean the user must always provide a concrete value before
export.

Each slot should distinguish these states:

| State | Meaning |
| --- | --- |
| provided | A value is present and has a source. |
| not_provided | The user or producer did not provide a value. |
| unknown | The system inspected available evidence but could not determine a value. |
| not_applicable | The slot does not apply to this measurement. |
| redacted | A value exists but is intentionally withheld for the sharing boundary. |

Missing fields with no status are producer failures. Explicit missing-value
states are valid snapshot evidence.

## Completeness Views

Completeness levels are diagnostic views over the same manifest, not fixed
product gates for the first `JC-002` slice.

In stable experiment code, many runs from the same workflow may have identical
completeness. Users may not need to see levels unless they are asking what
context is missing, preparing a handoff, or debugging why a package is hard to
reuse.

The first slice should preserve enough slot status information to compute
views like these later:

| Level | Meaning |
| --- | --- |
| Valid snapshot | Selected data and stable source identity exist, and the manifest slots are present. |
| Analysis-readable snapshot | Data can be opened; axes, units, shapes, and sidecars are provided or explicitly missing. |
| Meeting-useful snapshot | Sample/device label, measurement label, time, important parameters, and purpose are provided or explicitly missing with warnings. |
| Internally verifiable snapshot | Tier 3 references are sufficient for an internal reviewer to trace setup, calibration, code, or correction context. |

These names are provisional. A later UI or policy layer may let labs define
their own completeness profiles, required fields, and warning groups. The
fixture should check that missing information can be surfaced by profile; it
should not require fixed built-in levels to become user-facing product
concepts.

## Sharing Boundary

Ordinary internal handoff can preserve more full-fidelity context than public
or external support sharing. Public-safe or external packages may need
redaction of local paths, machine names, instrument addresses, user names,
sample identifiers, and lab-specific details.

Redaction is a later sharing-boundary concern. The first `JC-002` slice should
record whether a field is provided, not provided, unknown, not applicable, or
redacted, without defining a full permission or redaction system.

Minimum redaction invariants still apply. Public or external snapshots should
redact private absolute paths, local usernames, machine names, instrument
addresses, internal network locations, sample identifiers, and lab-only notes
by default unless an explicit policy allows sharing them. Redaction must not
erase the fact that a value existed.

## Support And Debug View

The first fixture should preserve enough information for a lightweight local
support/debug view:

- what this snapshot is: snapshot ID, creation time, source system, selected
  runs, and group label;
- whether it can open: primary data and required sidecar presence checks;
- what is missing: Tier 1 and Tier 2 warning list;
- what was excluded: unknown-role or advanced artifacts not copied;
- whether it can be shared: redaction and sensitive-field summary.

This view can be a generated summary, test output, or prototype screen. It is
not a full support workflow or permission system.

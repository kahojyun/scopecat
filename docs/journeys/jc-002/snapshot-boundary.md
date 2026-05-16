# JC-002 Snapshot Boundary

## Status

Draft boundary for fixture validation. This is not a stable manifest schema,
reader API, storage model, export format, UI spec, or accepted decision.

## Definition

A handoff snapshot is an immutable, portable, pre-analysis package containing
selected experiment data plus enough context to read, plot, and explain the
data on another computer.

```text
control computer
  -> user selects runs or datasets
  -> Scopecat packages already-known artifacts and context
  -> analysis computer
  -> user reads and analyzes snapshot
  -> derived figures, reports, fits, and slides are produced separately
```

Scopecat does not manage execution of the user's analysis code in this slice.

## Consumer Target

At validation level, a copied snapshot should support:

- opening locally without network, cloud login, or control-PC access;
- listing selected runs, artifact roles, warnings, and missing context;
- loading one run and a selected group with data, axes, units, labels, and
  required sidecars;
- handing plot-ready data and labels to a plotting component.

The local GUI and Python-reader-like paths are validation targets, not final UI
or API contracts.

## Include By Default

The snapshot should include or explicitly account for:

- snapshot identity and creation time;
- selected run or dataset source identity;
- selected-run group identity, order, labels, and selected reason when present;
- primary data needed for analysis;
- read sidecars required to open or interpret the primary data;
- axes, units, shapes, value labels, timestamp, and measurement label;
- sample, device, chip, or measurement-object labels when available;
- important parameter summaries when available;
- calibration, correction, or companion-artifact references when relevant;
- original source path evidence as provenance, not as a portable read path;
- warnings for missing, unknown, ambiguous, excluded, or redacted context.

Inclusion is role-based, not file-extension-based. An `.npy` file can be
primary data, a required sidecar, a user-attached derived input, or an analysis
output depending on role.

## Exclude By Default

The first snapshot boundary excludes:

- generated PDFs, plots, decks, reports, and publication arrays;
- fit-result tables and interpreted claims;
- notebook output state;
- generated derived artifacts during export;
- managed analysis environments;
- managed execution of user analysis scripts;
- active setup, parameter, configuration, or execution-state import;
- complete work-bundle export/import.

Later analysis outputs may be linked back to the snapshot by a separate
analysis-lineage journey or decision. This draft boundary does not define
append-only derived record semantics, storage, or mutation behavior.

## Optional Advanced Attachments

Advanced export options may copy user-attached derived inputs, selected
calibration or correction artifacts, selected notebooks or scripts as inert
files, internal verification references, or fuller local path evidence.

These are selection and packaging choices over known artifacts, not analysis
steps. Advanced options should be off by default and should carry role,
provenance, and warning text.

## Missing-Value Semantics

Required context slots do not mean users must always provide concrete values.
Slots should distinguish:

| State | Meaning |
| --- | --- |
| `provided` | A value is present and has a source. |
| `not_provided` | The user or producer did not provide a value. |
| `unknown` | Available evidence was inspected but no value could be determined. |
| `not_applicable` | The slot does not apply. |
| `redacted` | A value exists but is intentionally withheld for the sharing boundary. |

Missing fields with no status are producer failures. Explicit missing-value
states are valid snapshot evidence.

## Context Tiers

Use tiers as design guidance, not fixed product gates:

| Tier | Purpose | Handling |
| --- | --- | --- |
| Tier 1: read and plot | Make selected data openable and plottable. | Required slots; missing values become warnings. |
| Tier 2: meeting explanation | Help explain the measurement in ordinary lab discussion or handoff. | Required slots, but values may be `not_provided` or `unknown`. |
| Tier 3: internal verification | Support deeper internal debugging or audit. | Optional references by default; should not block ordinary snapshot creation. |

## Safety And Sharing

Snapshot export must be read-only against source runs and control state. It
must not write instruments, setup, parameters, registry state, live-control
state, notebooks, scripts, drivers, or analysis code.

Redaction belongs to explicit export or publish workflows, not to the ordinary
reader. The reader can show recorded redaction status, but it cannot guarantee
public safety because users can inspect snapshot files directly.

Public or external sharing should follow the project-level complexity boundary
in [`../../strategy/vision.md`](../../strategy/vision.md) and source-map
sharing guidance in
[`../../standards/jc-operating-standard.md`](../../standards/jc-operating-standard.md).

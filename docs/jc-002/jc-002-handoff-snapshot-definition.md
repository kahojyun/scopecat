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
  -> Scopecat creates immutable handoff snapshot
  -> analysis computer
  -> user reads and analyzes snapshot
  -> derived figures, PDFs, slides, and fit results are produced separately
```

## Include

The snapshot may include:

- selected run or dataset source identity;
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

## Exclude

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

## Context Tiers

Use tiers to separate what must travel with the data from what is useful only
for deeper investigation.

| Tier | Purpose | Typical fields | Handling |
| --- | --- | --- | --- |
| Tier 1: read and plot | Make the selected data openable and plottable on another computer. | Source ID, primary data, required sidecars, axis names, units, shape, timestamp, measurement label, original source path evidence. | Required manifest slots. Missing values should become explicit warnings. |
| Tier 2: meeting explanation | Help a user explain the measurement in lab discussion, slides, or ordinary handoff. | Sample/device label, measurement-object label, purpose note, selected reason, important parameters, relevant calibration/correction references. | Required slots for a meeting-useful snapshot, but user input may be explicitly not provided. |
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

## Validity Levels

Snapshots can be useful at different completeness levels:

| Level | Meaning |
| --- | --- |
| Valid snapshot | Selected data and stable source identity exist, and the manifest slots are present. |
| Analysis-readable snapshot | Data can be opened; axes, units, shapes, and sidecars are provided or explicitly missing. |
| Meeting-useful snapshot | Sample/device label, measurement label, time, important parameters, and purpose are provided or explicitly missing with warnings. |
| Internally verifiable snapshot | Tier 3 references are sufficient for an internal reviewer to trace setup, calibration, code, or correction context. |

The first `JC-002` slice should target analysis-readable and meeting-useful
snapshots. Internally verifiable snapshots are valuable but should not become
the default ceremony for every handoff.

## Sharing Boundary

Ordinary internal handoff can preserve more full-fidelity context than public
or external support sharing. Public-safe or external packages may need
redaction of local paths, machine names, instrument addresses, user names,
sample identifiers, and lab-specific details.

Redaction is a later sharing-boundary concern. The first `JC-002` slice should
record whether a field is provided, not provided, unknown, not applicable, or
redacted, without defining a full permission or redaction system.

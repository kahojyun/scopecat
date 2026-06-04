# Brownfield Current-State Assessment

## Status

Current as-is assessment for Scopecat's brownfield adoption context.

## Purpose

Describe the existing lab workflow and artifact reality that Scopecat must
adopt around. This is an as-is assessment, not a target journey map, transition
architecture, migration plan, implementation register, or evidence archive.

This document intentionally records patterns, not private local file listings.
The local sample corpus is used as a current-state reference, but stable docs
should avoid carrying private paths, hostnames, lab identifiers, or full raw
file inventories.

## Current-State Summary

The current environment is a mixed research-code and measurement-artifact
workspace rather than a clean product integration surface.

Observed patterns include:

- notebooks, Python scripts, helper packages, instrument-driver code, generated
  data, logs, workbooks, presentations, archives, backups, and copied folders
  living near each other;
- multiple similar project trees that appear to represent related hardware,
  cooldown, board, or experiment variants;
- repeated backup folders and dated file variants used as informal versioning;
- measurement data stored in different shapes, including CSV-like tables,
  NumPy arrays, JSON-like records, reports, and notebook outputs;
- parameter, setup, wiring, and analysis context spread across workbooks,
  scripts, notebooks, folders, and human naming conventions;
- experiment-code context stored as editable folders rather than a single
  trusted versioned artifact;
- driver/service code, experiment scripts, plotting utilities, and analysis
  helpers sharing the same broad workspace;
- output artifacts that are useful to humans but do not declare a stable
  machine-readable boundary for selection, handoff, review, or import.

## Current User Work Patterns

### Measurement Selection And Handoff

Users often need to identify a useful run or result from a mixture of data
files, notebooks, sidecar notes, reports, and folder structure.

Current pressure:

- useful measurement identity is inferred from filenames, folders, notebook
  cells, IDs, or human memory;
- transformed data and primary data can be hard to distinguish later;
- moving a result to another computer or collaborator risks losing context;
- the receiver may need to trust folder residue before they can inspect the
  data.

### Prepare A Manual Run

Users inspect parameter files, setup notes, wiring spreadsheets, code folders,
and environment state before running.

Current pressure:

- no single reviewable pre-run package owns the selected context;
- existing systems remain authoritative for hardware apply and run start;
- evidence about readiness is scattered;
- notebooks and local scripts can hide which context was actually used.

### Instrument And Service Readiness

Users often check whether instruments, services, drivers, environments, or
helper processes are ready enough before they trust a run.

Current pressure:

- readiness checks may live in scripts, notebooks, GUIs, logs, or operator
  habits rather than a stable review surface;
- failure recovery can require local knowledge about drivers, services,
  hardware state, or lab-specific restart order;
- Scopecat can record bounded readiness evidence, but current-state readiness
  does not imply Scopecat owns hardware safety or recovery.

### Calibration Continuation

Calibration work often depends on interrupted notebook state, fit previews,
manual actions, proposed writes, and downstream blocking decisions.

Current pressure:

- continuation state is difficult to inspect after interruption;
- proposed writes and accepted writes can be separated from later measurement
  context;
- fit review and retry decisions are not durable product objects;
- replacing execution ownership too early would create hardware-control risk.

### Running Measurement Inspection

Long-running measurements may expose partial data or progress through scripts,
temporary files, plots, or notebook output.

Current pressure:

- partial-but-useful data can be available before full completion;
- readiness and completeness are not always explicit;
- monitoring needs are real, but execution and scan control remain owned by the
  measurement code.

### Post-Run Analysis And Reporting

After a run, users often analyze, plot, summarize, and report selected results
before deciding whether the data is worth preserving, comparing, or handing off.

Current pressure:

- analysis artifacts can be mixed with primary data, transformed data,
  notebooks, figures, reports, and presentation material;
- selected "useful" results may be identified after several exploratory plots
  or notebook edits;
- later handoff or comparison depends on knowing which data is primary, which
  artifacts are derived, and which context is missing.

### Experiment Code Recovery

Code context is often reconstructed from copied folders, notebooks, helper
libraries, local naming conventions, backups, and editable working trees.

Current pressure:

- the code that mattered for a run may not be a clean Git commit;
- notebooks, helper modules, and generated environment files may all be
  relevant;
- a folder can be useful evidence without being a trustworthy execution
  environment;
- users need record, compare, and materialization paths before full execution
  ownership.

### Reference Comparison

Users compare current state against last-working or notable references by
opening files, notebooks, setup notes, and memory.

Current pressure:

- changed, missing, unverified, and not-compared facts are easy to collapse
  into vague gap language;
- reference goodness is user/domain judgment, not something Scopecat should
  claim by default;
- objective comparison needs declared context boundaries.

## Current-State Constraints

- Scopecat should not assume it can parse every legacy artifact shape.
- Scopecat should not infer hardware truth, setup truth, or scientific validity
  from local filenames or folder structure.
- Scopecat should not execute current-state scripts during static analysis or
  discovery.
- Scopecat should treat local evidence as a guide for product pressure, not as
  the target product model.
- Portable/export artifacts need stronger managed-reference validation and
  redaction than local internal review surfaces.

## Update Rule

Update this assessment when a new current-state pattern changes Scopecat's
brownfield assumptions.

Do not use this document to track target journeys, adoption paths, validation
maturity, implementation entrypoints, tests, or raw local file inventories.

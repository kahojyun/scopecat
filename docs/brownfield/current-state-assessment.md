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
- repeated backup folders, notebook checkpoints, copied package folders, and
  dated file variants used as informal versioning;
- measurement data stored in different shapes, including CSV-like tables,
  NumPy arrays, JSON-like records, reports, and notebook outputs;
- parameter, registry, setup, wiring, and analysis context spread across JSON
  files, lock files, workbooks, scripts, notebooks, folders, and human naming
  conventions;
- experiment-code context stored as editable folders rather than a single
  trusted versioned artifact;
- driver/service code, experiment scripts, plotting utilities, and analysis
  helpers sharing the same broad workspace;
- presentation, plotting, and processing artifacts co-located with primary data
  and experiment code, suggesting review and reporting are part of the same
  practical work surface;
- output artifacts that are useful to humans but do not declare a stable
  machine-readable boundary for selection, handoff, review, or import.

## Current User Work Patterns

### Record Or Adopt A Measurement

Users need to make externally produced or legacy-backed run facts visible
without replacing the scripts, notebooks, or systems that produced them.

Current pressure:

- source identity, operator intent, primary data, transformed data, and context
  references are often inferred from nearby files and naming conventions;
- useful records may begin as a folder, notebook output, dated table, or
  manually selected data artifact rather than a product-owned record;
- adopting a measurement requires preserving source posture without claiming raw
  source semantics, legacy execution, or scientific validity;
- primary data, parameter snapshots, setup references, and analysis artifacts may
  need to be linked before the record is ready for downstream use.

### Share A Selected Measurement

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

### Parameter Registry And Setup Maintenance

Users maintain parameter, registry, wiring, and setup snapshots as practical
working artifacts across run preparation, calibration, and later analysis.

Current pressure:

- multiple dated or variant parameter and registry files can coexist;
- lock files or sidecar files may indicate local editing or runtime state, but
  they do not by themselves prove current hardware state;
- setup and wiring context often lives in workbooks or notes outside the
  scripts that consume parameters;
- users may need parameter history, comparison, or plotting, but that work
  should remain a Parameter State capability use case unless it becomes an
  independent product journey.

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

### Review And Finalize A Completed Measurement

After a run, users often analyze, plot, summarize, and report selected results
before deciding whether the data is worth preserving, comparing, or handing off.

Current pressure:

- analysis artifacts can be mixed with primary data, transformed data,
  notebooks, figures, reports, and presentation material;
- selected "useful" results may be identified after several exploratory plots
  or notebook edits;
- later handoff or comparison depends on knowing which data is primary, which
  artifacts are derived, which review notes matter, and which context is
  missing;
- static reports or presentations can be useful review evidence, but they should
  not replace record-local source identity, primary-data references, or explicit
  operator review receipts.

### Reproduce Or Rerun From A Reference

Users reconstruct a prior or known-good run by combining reference selection,
code context, parameter/setup context, and local environment evidence.

Current pressure:

- the code that mattered for a run may not be a clean Git commit;
- notebooks, helper modules, and generated environment files may all be
  relevant;
- a folder can be useful evidence without being a trustworthy execution
  environment;
- changed, missing, unverified, and not-compared facts are easy to collapse
  into vague gap language;
- reference goodness is user/domain judgment, not something Scopecat should
  claim by default;
- objective comparison needs declared context boundaries;
- users need record, compare, and materialization paths before full execution
  ownership.

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

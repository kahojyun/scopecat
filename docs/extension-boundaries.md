# Extension Boundaries

Scopecat core stays domain-neutral. Domain-shaped examples, instrument
providers, compiler policy, and reusable analysis logic belong in example
support packages, private adapters, or future extension packages until a real
boundary is worth freezing.

## Core Boundary

Core owns generic workflow records and APIs:

- quantities, relation expressions, diagnostics, parameters, and experiment
  specs;
- planning, dry-run previews, execution records, result contracts, and storage
  references;
- `Workspace`, `Experiment`, `Run`, `Data`, `Analysis`, `AnalysisStep`,
  candidate configs, comparisons, and structured overviews.

Core must not import demo packages, private lab packages, or domain-specific
vocabulary modules.

## Example Packages

Example support packages are teaching, UX validation, and boundary-test code.
They may mix workflows, fixtures, virtual providers, helper functions, and
domain vocabulary when that keeps examples runnable and understandable.

The current quantum demo support package is not a stable domain extension. It
may contain readout calibration workflows, IQ analysis, sample templates,
virtual lab providers, notebook helpers, and update-loop examples because it
is local example support code.

Import guard tests should continue to fail if core imports the demo package or
if demo vocabulary leaks into the public core surface.

## Domain Extraction

Do not extract a domain package until the extracted boundary is smaller,
clearer, and more reusable than the example support package.

Extraction is justified only when the candidate package has:

- a deliberate public facade;
- package-owned artifact kinds and diagnostic prefixes;
- fixtures assigned to package tests, examples, or core boundary contracts;
- relation functions registered through stable function ids when needed;
- tests that pass without private core imports;
- a version policy for the compatible core range.

The first extracted package should start with foundational building blocks:
identifiers, domain records, serializers, artifact helpers, validation helpers,
and compiler-neutral payloads.

Do not start an extracted package with notebook examples, virtual lab providers,
calibration campaigns, candidate review policy, or update loops. Those stay in
examples or private workflow packages until their public contract is clear.

Creating a real extension package creates a compatibility obligation. Before
that happens, define supported Python versions, public modules, stable artifact
kinds, diagnostic prefixes, fixture expectations, and deprecation policy.

## Adapter Boundary

Adapters preserve external behavior while translating useful state into typed
Scopecat records.

Adapter responsibilities include:

- config and input validation;
- imports from CSV, XLSX, JSON, registry, or private runner formats;
- native instrument execution and runner translation;
- run metadata capture;
- dry-run behavior;
- preservation of raw external outputs as artifacts;
- structured measurement recording when feasible;
- diagnostics that explain what could not be translated.

Adapters may depend on external systems. Core models must not become shaped
around adapter compatibility.

## GUI And Workbench Boundary

A GUI workbench should present the same objects notebook and script users
already use:

```text
Workspace -> Experiment -> Run -> Data -> Analysis -> CandidateConfig -> Comparison -> Overview
```

The GUI may add navigation, filtering, and review affordances, but it should
not add GUI-only workflow records, artifact indexes, candidate config models,
or analysis state.

Workbench screens should resolve artifacts by `Artifact.id` first. Paths are
display and storage details, not navigation keys.

GUI write actions should be reproducible from notebook code:

- save manual analysis as an `Analysis` artifact;
- review a `CandidateConfig`;
- run a follow-up `Experiment` with a reviewed candidate config;
- compare runs;
- save user context or derived analysis outputs as typed artifacts.

If an action cannot be represented through `Workspace`, `Run`, `Data`,
`Analysis`, `CandidateConfig`, and typed artifacts, it is not ready for the GUI.

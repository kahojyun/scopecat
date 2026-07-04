# Extension Boundaries

Status: target design

Scopecat core stays domain-neutral. Domain vocabulary, pulse/circuit/program
semantics, compiler policy, instrument drivers, legacy runner behavior, and
GUI affordances live outside core unless a small generic boundary has been
proven by repeated real workflows.

## Core Boundary

Core owns generic records and APIs:

- quantities, units, entity refs, relation/scalar expressions, and diagnostics;
- config snapshots, parameter state, patches, change sets, candidate snapshots,
  and deterministic derived-view contracts;
- experiment modules, templates, run requests, closed experiment specs, plans,
  point sources, point identity, record specs, and result contracts;
- program refs, program artifacts, generic compiler-adapter records, device
  program records, and runtime command records;
- run manifests, events, artifacts, analysis records, candidates, comparisons,
  reviews, and storage refs;
- generic instrument and instrument-group boundary protocols.

Core must not import demo packages, private lab packages, or domain-specific
extension packages. Core docs and examples must not expose private machine
names, local paths, instrument addresses, chip labels, or lab-specific ids as
public architecture.

## Domain Extensions

Domain extensions own domain vocabulary and semantics. A future
`scopecat-quantum` package, for example, may own:

- qubit, resonator, coupler, line, sample, gate, measurement, reset, and
  feedback vocabulary;
- quantum program IR and compiler rules;
- pulse and waveform conventions;
- calibration lookup tables and domain validators;
- classifier artifacts and readout schemas;
- adapters to Qiskit, OpenQASM, MMCS, LabRAD runners, or backend-native
  program formats.

Core should only provide generic carriers:

```text
ProgramRef
ProgramArtifact
ResourceRef
CompilerAdapter
BackendProgram
DeviceProgram
ResultContract
```

Do not put `QubitSpec`, `GateSpec`, `PulseSpec`, `CircuitSpec`, or
feedback-specific semantics in core.

## Code Island Before IR

Complex domain programs should start as opaque or backend-native program
artifacts when the stable IR boundary is not yet proven.

Pure code islands may handle:

- sequence construction;
- pulse or waveform generation;
- calibration-derived program generation;
- backend-native program generation;
- analysis-to-candidate calculation.

They must not connect to hardware, upload, play, acquire, write accepted
config, mutate registries, or write private data stores. Their boundary must
declare typed inputs, typed outputs or artifacts, provenance, fingerprint,
dependencies, seeds, and determinism level.

Repeated stable semantics can later be promoted into a domain extension IR.

## Example Packages

Example support packages are teaching, UX validation, and boundary-test code.
They may mix workflows, fixtures, virtual providers, helper functions, and
domain vocabulary when that keeps examples runnable and understandable.

An example support package is not a stable domain extension. It may contain
calibration workflows, analysis helpers, sample templates, virtual lab
providers, notebook helpers, and update-loop examples because it is local
example support code.

Import guard tests should fail if core imports example packages or if example
vocabulary leaks into the public core surface.

## Domain Extraction

Do not extract a domain package until the extracted boundary is smaller,
clearer, and more reusable than the example support package.

Extraction is justified only when the candidate package has:

- a deliberate public facade;
- package-owned artifact kinds and diagnostic prefixes;
- fixtures assigned to package tests, examples, or core boundary contracts;
- stable function ids for registered pure functions when needed;
- tests that pass without private core imports;
- a version policy for compatible core ranges;
- a clear deprecation and schema migration policy.

Start extracted packages with foundational building blocks: identifiers,
domain records, serializers, artifact helpers, validators, compiler-neutral
payloads, and well-tested compiler adapters. Do not start with notebook flows,
virtual lab providers, campaign policy, or config activation policy.

## Instrument And Backend Boundary

Instrument adapters own side effects. They should expose capabilities and
execute device-local commands. They should not know complete experiment
semantics, config registries, analysis policy, candidate config review, or GUI
state.

Instrument groups own coordinated device-stack behavior:

- shared clock and trigger topology;
- virtual fields and products;
- logical-channel routing;
- group uploads, arms, triggers, readbacks, barriers, and acquisition;
- resource lease and synchronization metadata.

Runtime and coordinators own desired-state diffing, command scheduling,
retry/resume, crash recovery, mixed backend strategy, and result validation.

## Legacy Boundary

Legacy support has two preferred forms.

`RunScope` / `TraceScope` captures evidence from existing notebooks and
scripts. This is the default migration path for systems without a stable
structured execution boundary.

Adapters may translate stable legacy batch runners or backend programs into
Scopecat records when the runner has a clear input/output contract. Such
adapters are optional boundary code. They must not shape core records around
legacy compatibility.

Legacy side effects that should not enter core contracts include hardware
connection/setup, upload/play/acquire, registry mutation, Data Vault writes,
GUI/plotter state, notebook globals, and background services.

## GUI And Workbench Boundary

A GUI workbench should present the same durable objects notebook and script
users use:

```text
Workspace
  -> Template / RunRequest
  -> Run
  -> Data
  -> Analysis
  -> CandidateConfig
  -> Comparison
  -> Overview
```

The GUI may add navigation, filtering, plotting, diffing, and review
affordances, but it should not create GUI-only workflow records, artifact
indexes, candidate models, or analysis state.

Workbench screens should resolve artifacts by `RunArtifactEntry.id` first. Paths are
display and storage details, not navigation keys.

GUI write actions should be reproducible from Python APIs:

- create a run request;
- preview or validate explicitly, or run a structured experiment;
- open a run scope for capture;
- save manual analysis;
- run a follow-up candidate;
- compare runs and review outcomes;
- activate a candidate config;
- save operator context or derived outputs as typed artifacts.

If an action cannot be represented through core workflow records and typed
artifacts, it is not ready for the GUI.

# Automation Architecture Notes for a Progressive Experimental Automation Platform

## Status

Quarantined

## Source

Historical automation architecture discussion. Inputs included interview-based
pain-point analysis of the legacy experimental codebase, ongoing external
reference collection, and design precedents available at the time of
discussion.

## Summary

This note captures an early architecture framing for a progressively adoptable
experimental automation platform. It includes candidate capability boundaries,
adoption ideas, documentation structure, open questions, and technical spike
ideas. Its lasting value is the broad capability pressure: replacing
manual-discipline recordkeeping with reliable automatic versioned records, then
using those records to improve configuration, code provenance, scan semantics,
execution readiness, lineage, handoff, and later automation.

## Current Use

- [`extracted/research-acceptance-readiness-triage.md`](extracted/research-acceptance-readiness-triage.md)
  classifies this note's guardrails, evidence-backed inferences, adoption
  hypotheses, future pressure, ADR-gated directions, and rejected upfront
  directions.
- `../evidence-and-pain-point-inventory.md` preserves the capability pressures
  behind this note while keeping subsystem order, implementation scope, and
  scaffold shape unaccepted.
- No accepted product plan, architecture contract, or decision has been
  promoted from this note yet.

## Remaining Value

Use this note for historical context, vocabulary candidates, hypothesis
discovery, and provenance when distilling a smaller architecture extraction.
Do not use it as the current product plan. Sections that suggest a first
implementation direction, maturity order, subsystem scaffold, or "do first"
sequence are hypotheses to revalidate through journey-first discovery before
promotion into durable product, architecture, or decision documents.

Do preserve the problem pressure behind its capabilities. Measurement History
is useful and comparatively easy to adopt, but over-centering it would risk a
measurement-system-shaped internal tool with weak differentiation. The other
capability pressures in this note should be used to challenge that bias before
W2 selects a first journey.

Retain this note longer than the predecessor project import, but delete it
after the first selected journey has produced a smaller capability/adoption
hypothesis note, architecture-question list, and ADR trigger list. It should
not remain as a regular source once capability specs or implementation plans
start, because its subsystem map and migration order can bias current design.

---

## 1. Executive Summary

The emerging design is not a single replacement application for the old experimental system. It is better understood as a **progressively adoptable experimental automation platform** composed of several independently useful foundational capabilities.

The original three-system framing was:

1. **Measurement History**
2. **Parameter Memory**
3. **Managed Code Runner**

During the design discussion, several additional needs became visible:

- instrument communication lifecycle management;
- resource leases to prevent conflicting experimental execution;
- shared laboratory code and device-code versioning;
- declarative parameter scan planning;
- local design and preview with remote execution.

This suggests a broader architecture:

```text
Foundational capabilities:
  1. Measurement History
  2. Scan Framework
  3. Parameter Memory
  4. Code Asset Registry
  5. Instrument Runtime
  6. Managed Code Runner

Composition capabilities:
  7. Workflow / Orchestration Layer
  8. Remote Execution Coordinator
```

The most important product principle is:

```text
Each foundational capability should be independently useful,
but composition should create the full experimental automation platform value.
```

This principle is essential because the platform is intended to replace old experimental code gradually. Users should not be forced into a big-bang migration.

---

## 2. Current Project Context

The project is in a **greenfield design phase**. No strong implementation commitments should be assumed yet. The design should therefore remain explicit about:

- hypotheses versus settled decisions;
- standalone adoption paths;
- legacy migration constraints;
- unknowns that require further interviews or technical spikes;
- external reference materials still being collected.

At this stage, documentation should not prematurely harden into implementation specifications for every subsystem. It should instead support:

1. parallel design work;
2. clear subsystem ownership;
3. future migration planning;
4. reduced Git conflicts;
5. traceability from interview pain points to architectural decisions.

---

## 3. Core Design Reflection

The strongest architectural insight from the discussion is that the platform should not be designed as a monolithic experiment runner.

Legacy experimental systems often contain a tangled mix of:

- acquisition scripts;
- nested scan loops;
- copied device drivers;
- ad-hoc parameter files;
- notebooks;
- manual calibration notes;
- inconsistent data formats;
- local-only execution assumptions;
- duplicated code across experiments;
- implicit knowledge about instrument state and resource usage.

A monolithic replacement would require users to migrate everything at once. That is unlikely to succeed.

Instead, the platform should be designed around **incremental replacement of legacy pain points**. Each foundational subsystem should solve one category of pain independently, while exposing optional integration points for deeper composition.

The corresponding rule is:

```text
Core paths must work alone.
Integrated paths add stronger provenance, safety, automation, and reproducibility.
```

---

## 4. Foundational Capability Map

### 4.1 Measurement History

**Core responsibility:** Record what happened.

Measurement History owns:

- experiment runs;
- raw datasets;
- derived datasets;
- imported legacy datasets;
- scan-point records;
- dataset lineage;
- run metadata;
- historical browsing and querying;
- links to parameter snapshots, execution records, resource leases, and code versions.

It should not own:

- long-lived parameter definitions;
- live instrument control;
- code execution;
- code version identity;
- workflow decisions.

**Standalone adoption story:**

Users continue running old experimental scripts but write or import data into the new Measurement History system. This immediately improves data storage, browsing, provenance, and dataset consistency without requiring a full migration.

**Integrated value:**

When integrated, a run can reference:

- the parameter snapshot used;
- the scan plan used;
- the code version executed;
- the execution record;
- the resource lease;
- the instrument state snapshot;
- raw and derived datasets.

---

### 4.2 Scan Framework

**Core responsibility:** Structure experimental scan semantics.

The Scan Framework owns:

- scan plans;
- scan variables;
- fixed experiment-local parameters;
- scan-point expansion;
- parameter binding;
- desired instrument-state rendering;
- state preview;
- state diffing;
- acquisition-block structure;
- debug/dry-run output;
- scan metadata emitted to Measurement History.

It should not own:

- durable calibration parameters;
- live instrument leases;
- driver lifecycle;
- code asset identity;
- execution environments;
- full multi-step workflow orchestration.

**Standalone adoption story:**

Users replace ad-hoc nested loops with structured scan plans while still using old device drivers and old data-saving code. The framework can expand scan variables, render target instrument states, and provide preview/debug output without touching real hardware.

Example standalone mode:

```python
scan = ScanPlan(
    axes={
        "freq": linspace(6.6e9, 6.9e9, 301),
        "power": [-40, -35, -30],
    },
    fixed={
        "if_bandwidth": 1e3,
        "averages": 10,
    },
    render=lambda p: {
        "vna.main": {
            "center_frequency": p.freq,
            "power": p.power,
            "if_bandwidth": p.if_bandwidth,
            "averages": p.averages,
        }
    },
)

scan.preview(point=0)

for point, desired_state in scan.iter_rendered_states():
    legacy_set_instruments(desired_state)
    data = legacy_measure()
    legacy_save(data)
```

**Integrated value:**

The same scan plan can later:

- bind values from Parameter Memory;
- request resource leases from Instrument Runtime;
- commit desired states to real instruments;
- execute acquisition hooks through Managed Code Runner;
- write structured scan-point records to Measurement History;
- reference reusable templates or renderers from Code Asset Registry.

---

### 4.3 Parameter Memory

**Core responsibility:** Record durable parameter knowledge.

Parameter Memory owns:

- parameter schemas;
- parameter slots;
- parameter sets;
- immutable parameter snapshots;
- calibration state;
- parameter update proposals;
- parameter history;
- typed helper generation, if needed later.

It should not own:

- scan-local variables;
- live instrument state;
- resource leases;
- code execution;
- measurement datasets.

**Standalone adoption story:**

Users continue using old scripts but start reading parameters from Parameter Memory or exporting snapshots into formats consumed by old code. This replaces scattered YAML, JSON, Python configs, notebooks, and calibration notes.

**Integrated value:**

A Measurement History run can reference the exact ParameterSnapshot used. Analysis or calibration code can propose updates to Parameter Memory, which users may accept to create new snapshots.

---

### 4.4 Code Asset Registry

**Core responsibility:** Manage code identity and versioned reusable code assets.

Code Asset Registry owns:

- shared laboratory code assets;
- experiment scripts;
- analysis scripts;
- fitting routines;
- calibration routines;
- instrument drivers;
- instrument service modules;
- workflow or scan templates;
- source references;
- code versions;
- content hashes;
- entrypoints;
- compatibility metadata;
- publishing or validation metadata.

It should not own:

- execution records;
- live instrument services;
- datasets;
- resource leases;
- environment snapshots, except as metadata references.

**Standalone adoption story:**

The laboratory can stop copying scripts and drivers across directories. Code remains in external Git repositories, local paths, or packages, while the registry records stable asset identity, version references, entrypoints, and metadata.

**Integrated value:**

Managed Code Runner uses CodeAsset references to execute exact code versions. Instrument Runtime uses CodeAsset references to load driver or service versions. Measurement History records which code versions were involved in a run.

**Key boundary rule:**

```text
Code Asset Registry owns code identity.
Managed Code Runner owns execution identity.
Instrument Runtime owns live service identity.
```

---

### 4.5 Instrument Runtime

**Core responsibility:** Manage live laboratory resources.

Instrument Runtime owns:

- instrument registry;
- lab resource registry;
- instrument communication service lifecycle;
- device driver/service binding;
- live instrument health;
- resource leases;
- exclusive or shared access modes;
- lease renewal and expiration;
- conflict prevention;
- actual state validation and application;
- live state snapshots.

It should not own:

- durable parameter knowledge;
- general code version identity;
- experiment scan semantics;
- datasets;
- code execution records.

**Standalone adoption story:**

Users continue using old experimental code but acquire leases before touching instruments. This prevents two experiments from accidentally controlling the same device or setup at the same time.

**Integrated value:**

Scan Framework renders desired states. Instrument Runtime validates and applies those states to live instruments, under a resource lease, and reports actual state or errors.

---

### 4.6 Managed Code Runner

**Core responsibility:** Execute code in a controlled, observable, and reproducible way.

Managed Code Runner owns:

- execution plans;
- execution records;
- environment snapshots;
- stdout/stderr capture;
- artifacts;
- process supervision;
- resource limits;
- execution status;
- cancellation;
- batch or remote execution mechanics.

It should not own:

- general code asset identity;
- live instrument leases;
- measurement datasets;
- durable parameter definitions;
- experiment scan semantics.

**Standalone adoption story:**

Users run old analysis, fitting, or acquisition scripts through the runner to capture logs, artifacts, environment information, and execution status, without yet adopting the full platform.

**Integrated value:**

The runner executes acquisition hooks, analysis hooks, custom renderers, or calibration tasks using exact CodeAsset versions and records execution provenance for Measurement History.

---

## 5. Composition Capabilities

### 5.1 Workflow / Orchestration Layer

The Workflow Layer composes multiple foundational capabilities into higher-level experimental procedures.

It owns:

- multi-step experiment protocols;
- coarse scan → fit → fine scan workflows;
- calibration loops;
- adaptive scans;
- human approval points;
- conditional branching;
- retry and fallback policies;
- cross-subsystem sequencing.

It should not absorb the domain responsibilities of foundational systems.

Boundary distinction:

```text
Scan Framework owns acquisition-block semantics.
Workflow Layer owns multi-step experiment protocols.
```

Example:

```text
Workflow:
  1. Run coarse spectroscopy scan.
  2. Fit peak.
  3. Run fine scan around fitted peak.
  4. Propose parameter update.
  5. Wait for user approval.

Scan Framework:
  Defines each scan block, expands scan points, renders desired instrument states.
```

---

### 5.2 Remote Execution Coordinator

The Remote Execution Coordinator receives frozen experiment plans from local clients and coordinates remote execution.

It owns:

- remote submission lifecycle;
- remote validation;
- lease acquisition coordination;
- execution startup;
- monitoring stream coordination;
- cancellation;
- pause/resume, if supported;
- finalization and cleanup.

It uses:

- Scan Framework remote runtime;
- Instrument Runtime;
- Managed Code Runner;
- Measurement History;
- Parameter Memory;
- Code Asset Registry.

It should not be the only way to use foundational systems. Local execution and standalone subsystem usage should remain possible.

---

## 6. Local Design / Preview and Remote Execution

A major design goal is to support the transition from local experimental execution to:

```text
Local design and preview → Remote validation → Remote execution → Local monitoring
```

This requires a clear separation between design-time and execution-time responsibilities.

### 6.1 Local Responsibilities

Local clients should support:

- editing scan plans;
- binding parameters;
- rendering desired states;
- previewing scan points;
- diffing planned states;
- estimating resource requirements;
- running dry-run validation;
- freezing an execution package;
- submitting to a remote coordinator;
- monitoring progress and results.

Local preview should not require access to real instruments.

### 6.2 Remote Responsibilities

Remote lab servers should support:

- revalidating frozen plans;
- resolving canonical parameter snapshots;
- resolving exact code versions;
- validating permissions;
- validating live instrument capabilities;
- acquiring leases;
- applying desired instrument states;
- executing acquisition and analysis code;
- writing canonical Measurement History records;
- streaming progress, logs, and data summaries.

### 6.3 Experiment Package / Remote Execution Plan

A portable, immutable intermediate artifact is required between local design and remote execution.

Suggested model:

```text
ExperimentPackage / RemoteExecutionPlan
  package_id
  author
  created_at
  scan_plan_snapshot
  parameter_snapshot_ref
  parameter_snapshot_hash
  code_asset_refs
  code_asset_hashes
  required_resources
  lease_policy
  expected_dataset_schema
  safety_constraints
  preview_summary
  plan_hash
  execution_policy
```

Key rule:

```text
Remote execution must execute the same plan that was locally previewed.
```

This implies:

- immutable plan representation;
- shared scan rendering semantics;
- hash validation;
- remote revalidation;
- actual state recording.

---

## 7. Desired State, Actual State, and Preview Semantics

The Scan Framework renders **desired instrument state**.

Instrument Runtime applies that desired state and returns **actual instrument state** or an apply result.

These must remain distinct.

Example:

```text
Desired state:
  vna.main.center_frequency = 6.700 GHz
  vna.main.power = -30 dBm

Actual state:
  vna.main.center_frequency = 6.700000001 GHz
  vna.main.power = -29.98 dBm
  settled = true
```

Measurement History should record at least:

- scan point identity;
- logical scan variables;
- desired state summary;
- actual state summary or acknowledgement;
- apply errors;
- dataset output;
- resource and execution references.

This distinction is necessary for reproducibility, safety, and debugging.

---

## 8. Progressive Adoption Strategy

The platform should support staged migration from old experimental code.

A plausible migration sequence is:

```text
1. Measurement History
2. Scan Framework
3. Parameter Memory
4. Instrument Runtime
5. Code Asset Registry
6. Managed Code Runner
7. Workflow / Orchestration
8. Remote Execution Coordinator
```

However, the exact sequence should be driven by interview results and the most severe legacy pain points.

Alternative early paths:

- If the main pain is data chaos: start with Measurement History.
- If the main pain is ad-hoc scan loops: start with Scan Framework.
- If the main pain is instrument conflicts: start with Instrument Runtime.
- If the main pain is copied scripts and drivers: start with Code Asset Registry.
- If the main pain is unreproducible execution: start with Managed Code Runner.

The important architectural point is that each capability has a standalone adoption path.

---

## 9. Design Maturity Matrix

Since the project is greenfield, not all capabilities should be specified with equal depth immediately.

Suggested initial maturity targets:

| Capability | Product | Domain | Architecture | Spec | Early Implementation Depth |
|---|---:|---:|---:|---:|---|
| Measurement History | Deep | Deep | Deep | Deep | High |
| Scan Framework | Deep | Deep | Medium-Deep | Medium-Deep | High |
| Parameter Memory | Medium-Deep | Deep | Medium | Medium | Medium |
| Instrument Runtime | Medium | Medium | Medium | Shallow-Medium | Medium |
| Code Asset Registry | Medium | Medium | Shallow-Medium | Shallow | Low-Medium |
| Managed Code Runner | Medium | Medium | Shallow-Medium | Shallow | Low-Medium |
| Workflow Layer | Draft | Draft | Shallow | Shallow | Low |
| Remote Execution Coordinator | Draft | Draft | Shallow | Shallow | Low |

The goal is not to advance every subsystem to implementation-ready status at once. The goal is to keep boundaries compatible while deepening the most valuable migration path first.

---

## 10. Documentation Strategy

The documentation should reflect parallel design while reducing Git conflicts.

Recommended structure:

```text
docs/
  README.md
  vision.md
  glossary.md
  system-map.md

  integration/
    composition-model.md
    data-ownership.md
    dependency-rules.md
    domain-boundaries.md
    cross-system-contracts.md
    release-staging.md

  remote-execution/
    local-authoring-remote-execution.md
    experiment-package.md
    remote-validation.md
    submission-lifecycle.md
    monitoring-and-cancellation.md
    security-and-permissions.md

  workflows/
    calibration-loop.md
    adaptive-scan-workflow.md
    batch-analysis-workflow.md

subsystems/
  measurement-history/
  scan-framework/
  parameter-memory/
  code-asset-registry/
  instrument-runtime/
  managed-code-runner/
```

Each subsystem should have:

```text
subsystems/<name>/
  README.md
  product/
    product-brief.md
    standalone-adoption.md
    user-stories.md
    non-goals.md
  domain/
    README.md
    <concept-card>.md
  architecture/
    README.md
    <architecture-topic>.md
  specs/
    <subsystem-prefix>-001-<topic>.md
  decisions/
    <SUBSYSTEM>-ADR-0001-<decision>.md
```

Concept cards should use a consistent template:

```markdown
# Concept Name

## Owner

## Purpose

## Identity

## Lifecycle

## References

## Does Not Own

## Migration Notes

## Open Questions
```

This file-per-concept structure reduces conflicts and makes it easier for multiple humans or agents to work in parallel.

---

## 11. Data Ownership Summary

| Concept | Owner |
|---|---|
| ExperimentRun | Measurement History |
| Dataset | Measurement History |
| DerivedDataset | Measurement History |
| ScanPointRecord | Measurement History |
| ScanPlan | Scan Framework |
| ScanVariable | Scan Framework |
| DesiredInstrumentState | Scan Framework |
| ActualInstrumentState | Instrument Runtime |
| ParameterSnapshot | Parameter Memory |
| ParameterUpdateProposal | Parameter Memory |
| CodeAsset | Code Asset Registry |
| CodeVersion | Code Asset Registry |
| CodeEntrypoint | Code Asset Registry |
| Instrument | Instrument Runtime |
| LabResource | Instrument Runtime |
| ResourceLease | Instrument Runtime |
| InstrumentService | Instrument Runtime |
| ExecutionRecord | Managed Code Runner |
| EnvironmentSnapshot | Managed Code Runner |
| Artifact | Managed Code Runner |
| WorkflowRun | Workflow / Orchestration |
| ExperimentPackage | Remote Execution / Integration Contract |

---

## 12. Dependency Rules

Suggested dependency rules:

```text
Measurement History:
  may reference other systems;
  must not require them for basic data recording.

Scan Framework:
  may run standalone;
  may optionally integrate with Parameter Memory, Instrument Runtime, Managed Code Runner, Code Asset Registry, and Measurement History.

Parameter Memory:
  owns durable parameters;
  must not depend on live instrument runtime or scan execution.

Code Asset Registry:
  owns code identity;
  must not execute code or manage live instruments.

Instrument Runtime:
  owns live resources, leases, and instrument service lifecycle;
  must not own durable parameter knowledge or general code identity.

Managed Code Runner:
  owns execution records and environment snapshots;
  must not own code asset identity or instrument lease policy.

Workflow Layer:
  may depend on all foundational systems.

Foundational systems:
  must not require the Workflow Layer for their core standalone use cases.
```

---

## 13. Feature Flags and Experimental Namespaces

Because public release maturity will differ across capabilities, the platform should support:

1. **feature flags** for product exposure;
2. **experimental namespaces** for API stability boundaries.

Example:

```text
features.measurement_history = stable
features.scan_framework = experimental
features.parameter_memory = experimental
features.instrument_runtime = hidden
features.code_asset_registry = hidden
features.managed_code_runner = hidden
```

Example API namespace pattern:

```python
from lab.measurement_history import Run, Dataset
from lab.scan import ScanPlan
from lab.experimental.parameters import ParameterStore
from lab.experimental.instrument_runtime import LeaseManager
from lab.experimental.runner import ManagedRunner
```

Feature flags control runtime/product exposure. Experimental namespaces communicate API compatibility expectations.

---

## 14. Research and Reference Collection Areas

Since the project is still collecting reference material, the following areas are worth investigating systematically.

### 14.1 Experimental Data and Provenance Systems

Look for references on:

- scientific data provenance;
- dataset lineage;
- run metadata;
- laboratory information management systems;
- experiment tracking systems;
- append-only measurement records;
- reproducible data acquisition.

Questions to answer:

- What metadata is essential for long-term reproducibility?
- How do existing systems represent runs, datasets, and derived datasets?
- What provenance models are too heavy for small laboratories?

### 14.2 Parameter and Calibration Management

Look for references on:

- immutable configuration snapshots;
- calibration history;
- parameter registries;
- typed parameter schemas;
- schema evolution;
- configuration reproducibility.

Questions to answer:

- Which parameters are durable knowledge versus experiment-local variables?
- How should calibration results become parameter update proposals?
- How much type structure is useful before the system becomes too rigid?

### 14.3 Scan Frameworks and Declarative Experiment Design

Look for references on:

- grid scans;
- adaptive scans;
- experiment plans;
- declarative instrument state models;
- dry-run preview;
- scan-point lineage;
- parameter-space exploration;
- domain-specific languages for experiments.

Questions to answer:

- What is the minimal scan representation that supports old-code migration?
- How should desired instrument state be represented?
- How much of the renderer should be declarative versus user-defined code?

### 14.4 Instrument Control and Resource Scheduling

Look for references on:

- instrument server architecture;
- device driver lifecycle;
- hardware resource leases;
- distributed locks;
- heartbeat-based lease expiration;
- service supervision;
- resource capability schemas.

Questions to answer:

- Should leases cover only instruments or also virtual lab resources?
- What lease modes are needed beyond exclusive control?
- How should actual instrument state be read back and recorded?

### 14.5 Code Asset and Laboratory Repository Management

Look for references on:

- internal package registries;
- code provenance;
- Git-based code asset tracking;
- entrypoint metadata;
- reviewed/validated code versions;
- device driver compatibility matrices.

Questions to answer:

- Is the first version a registry over external Git repos, or a hosting system?
- What metadata is needed for instrument drivers versus analysis scripts?
- How should code versions and execution environments be separated?

### 14.6 Managed Execution and Remote Experiment Execution

Look for references on:

- remote job execution;
- batch schedulers;
- sandboxing;
- execution artifacts;
- environment snapshots;
- remote monitoring;
- cancellation and failure recovery.

Questions to answer:

- What is the minimal remote execution coordinator?
- Should code be resolved remotely or uploaded as frozen bundles?
- What security model is acceptable for early prototypes?

---

## 15. Interview Analysis Mapping

Existing interview findings about the old codebase should be mapped into architecture hypotheses.

Suggested mapping format:

```markdown
# Legacy Pain Point

## Evidence

Interview excerpts, observed workflows, examples from the old codebase.

## Affected Workflows

Which experiments or users are affected?

## Root Cause Hypothesis

What system boundary or missing abstraction causes the pain?

## Candidate Capability

Which foundational capability addresses it?

## Migration Path

How can users adopt the new capability without full migration?

## Open Questions
```

Example:

```text
Pain point:
  Experiment scripts are copied into many directories and modified locally.

Candidate capability:
  Code Asset Registry.

Standalone migration:
  Register existing Git repositories and entrypoints without changing execution.

Integrated migration:
  Managed Code Runner executes registered code assets and records exact versions.
```

This approach keeps the design grounded in real user pain instead of speculative abstraction.

---

## 16. Near-Term Design Recommendations

### 16.1 Do First

1. Write `docs/vision.md` and `docs/system-map.md`.
2. Create product briefs for all foundational capabilities.
3. Write standalone adoption stories for each capability.
4. Create `docs/integration/data-ownership.md`.
5. Create `docs/integration/dependency-rules.md`.
6. Deepen Measurement History and Scan Framework first, because they strongly affect early migration and data model shape.
7. Keep Parameter Memory, Instrument Runtime, Code Asset Registry, and Managed Code Runner at contract/prototype depth initially.

### 16.2 Avoid Early

Avoid building:

- a full workflow engine too early;
- a general scheduler too early;
- a full Git hosting or package registry too early;
- a heavyweight sandboxing system before execution requirements are clear;
- a monolithic PRD that every subsystem edits;
- a single giant domain model document;
- a requirement that all subsystems be adopted together.

### 16.3 Technical Spikes Worth Running

Useful early spikes:

1. **Scan preview spike**
   Define a static grid scan and render target instrument state without hardware.

2. **Measurement History import spike**
   Import one representative legacy dataset and preserve metadata.

3. **Scan-to-history spike**
   Execute a simple scan loop and record structured scan points.

4. **Lease manager spike**
   Implement exclusive leases with TTL and conflict rejection.

5. **Code asset reference spike**
   Register a Git repo, commit hash, and entrypoint, without executing it.

6. **Remote dry-run spike**
   Generate an ExperimentPackage locally and validate it remotely without touching hardware.

---

## 17. Key Open Questions

### Product Questions

- Which legacy pain point is most urgent: data history, scan logic, parameter management, instrument conflicts, code duplication, or execution reproducibility?
- Who is the first user group: experiment authors, data analysts, instrument maintainers, or lab operators?
- Which subsystem can create the fastest visible value?

### Domain Questions

- What is the minimal sufficient representation of a scan plan?
- Which parameters are durable and which are experiment-local?
- How should derived datasets and fit results be represented?
- What is the boundary between analysis artifacts and derived measurement data?

### Architecture Questions

- Should the first Measurement History store be local, remote, or hybrid?
- Should remote execution receive frozen bundles or resolve code remotely?
- How strict should instrument state schemas be in early versions?
- Should resource leases support only exclusive mode initially?
- What is the minimum viable security model for remote execution?

### Migration Questions

- Which old scripts can be wrapped without modification?
- Which old scripts must be rewritten to fit the scan framework?
- How should old parameter files be imported?
- How should legacy driver copies be reconciled into Code Asset Registry?

---

## 18. Architectural Principles to Preserve

1. **Progressive adoption over big-bang migration.**
   Users must be able to adopt one capability at a time.

2. **Standalone value first, composition value second.**
   Every foundational capability needs an independent product story.

3. **Explicit ownership.**
   Every major concept should have a single owning subsystem.

4. **Optional integration points.**
   Integration references should be optional until the relevant subsystem is mature.

5. **Immutable references for reproducibility.**
   Parameter snapshots, code versions, scan plans, and execution packages should be frozen or hashable when used in a run.

6. **Preview and execution share semantics.**
   Local preview and remote execution must use the same plan representation and render semantics.

7. **Desired state is not actual state.**
   Desired instrument state rendered by the scan framework must be distinguished from actual state acknowledged by Instrument Runtime.

8. **Workflow should compose, not absorb.**
   The Workflow Layer coordinates foundational capabilities but should not own their core domain models.

9. **Remote execution must revalidate.**
   Remote execution should revalidate plans against canonical parameters, code versions, permissions, leases, and live instrument capabilities.

10. **Documentation should reflect subsystem boundaries.**
    Split documents by subsystem and concept to reduce conflicts and preserve design clarity.

---

## 19. Working Architecture Summary

The current working architecture can be summarized as:

```text
Local authoring side:
  - User edits scan plans and experiment intent.
  - Scan Framework expands parameters and renders desired states.
  - Local preview validates plan shape and debug output.
  - A frozen ExperimentPackage is produced.

Remote execution side:
  - Remote Execution Coordinator validates the package.
  - Parameter Memory resolves immutable snapshots.
  - Code Asset Registry resolves exact code versions.
  - Instrument Runtime acquires resource leases and manages live devices.
  - Managed Code Runner executes controlled hooks or scripts.
  - Measurement History records run, scan points, datasets, provenance, and outputs.

Composition side:
  - Workflow Layer chains scan blocks, analysis steps, calibration proposals, and human approvals.
```

The design remains greenfield and should be treated as a set of architectural hypotheses. The next step is to connect these hypotheses to interview evidence, reference material, and small technical spikes.

---

## 20. Suggested Next Deliverables

1. `docs/vision.md`
   One-page statement of the progressive experimental automation platform vision.

2. `docs/system-map.md`
   Visual and textual overview of the six foundational capabilities and two composition capabilities.

3. `docs/integration/data-ownership.md`
   Single source of truth for concept ownership.

4. `subsystems/measurement-history/product/product-brief.md`

5. `subsystems/scan-framework/product/product-brief.md`

6. `subsystems/scan-framework/domain/scan-plan.md`

7. `subsystems/measurement-history/domain/experiment-run.md`

8. `docs/remote-execution/experiment-package.md`

9. Interview-to-architecture mapping document.

10. Reference-material reading list grouped by capability.

---

## Appendix A: Short Glossary

**Measurement History**
System for recording experiment runs, datasets, lineage, and historical facts.

**Scan Framework**
Declarative experiment acquisition-block framework for scan variables, fixed parameters, desired state rendering, preview, and scan-point execution semantics.

**Parameter Memory**
Durable parameter, calibration, and immutable snapshot management system.

**Code Asset Registry**
Versioned registry of experiment code, analysis code, drivers, services, templates, and entrypoints.

**Instrument Runtime**
Live instrument service lifecycle and resource lease management system.

**Managed Code Runner**
Controlled code execution system that records execution status, logs, artifacts, and environments.

**Workflow / Orchestration Layer**
Composition layer for multi-step experiment protocols.

**Remote Execution Coordinator**
Service that validates and executes frozen experiment packages against remote laboratory resources.

**ExperimentPackage**
Immutable package representing locally designed and previewed experiment intent for remote execution.

**Desired Instrument State**
The target state rendered by the Scan Framework for a scan point.

**Actual Instrument State**
The state acknowledged or read back from Instrument Runtime after applying desired state.

---

## Appendix B: One-Sentence Design Thesis

A progressively adoptable experimental automation platform should turn legacy experimental scripts into structured, previewable, versioned, remotely executable experiment plans by separating data history, scan semantics, parameters, code assets, instrument runtime, and managed execution into independently useful but composable foundational capabilities.

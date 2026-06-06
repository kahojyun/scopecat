# Domain Model

## Status

Initial layered domain vocabulary.

## Purpose

Provide shared analysis language for architecture and future design while
keeping brownfield concepts separate from Scopecat transition concepts.

Use this document to classify terms and modeling boundaries. Use
[`../product/target-journeys.md`](../product/target-journeys.md) for canonical
journey/use-case ownership, [`../product/target-capabilities.md`](../product/target-capabilities.md)
for capability maturity, and ADRs when a concept becomes an accepted
architecture decision.

## Layers

| Layer | Meaning | Use For |
| --- | --- | --- |
| Brownfield vocabulary | Concepts already visible in the current lab workflow or legacy artifacts. | Ground architecture in current user work and prevent slice-shaped abstractions from leading the model. |
| Core Scopecat domain concepts | Scopecat concepts close to the user problem and likely to remain visible across entrypoints. | Design durable capability boundaries without claiming final schema. |
| Process and integration objects | Operation, review, audit, and handoff objects used to connect workflows and bounded contexts. | Model workflow seams and operation boundaries without over-promoting them to core entities. |
| Artifact descriptor objects | Objects that describe files, packages, storage records, or artifact sets. | Keep artifact structure separate from operation results and user decisions. |

## Brownfield Vocabulary

These are the starting concepts. They should appear in as-is analysis before
Scopecat transition terms are introduced.

| Concept | Brownfield Meaning | Architecture Pressure |
| --- | --- | --- |
| Operator notebook or script | The user-facing work surface that prepares, runs, inspects, analyzes, or reopens experiment work. | Notebooks can be both review surfaces and hardware-active entrypoints; Scopecat should not treat them as passive documents by default. |
| Experiment runner or driver | Local code and services that configure devices, execute sweeps, append rows, and clean up. | Existing runtime authority stays outside Scopecat until explicitly moved. |
| Data Vault-style dataset or numeric ID | Legacy recorded measurement identity and row storage used for reopen, plotting, and selected-run work. | Scopecat needs to preserve source identity without inheriting all legacy storage semantics. |
| Primary table or row data | Recorded measurement rows, chunks, or converted tables expected to support inspection. | Preview and import need explicit shape and source posture. |
| Partial or interrupted run | A run with useful rows or progress but incomplete lifecycle evidence. | Partial state can be normal, not automatically invalid. |
| Parameter file or registry entry | Active or copied JSON/registry facts used to configure experiments and interpret results. | Point-in-time parameter facts can drift from generated companions and later writes. |
| Setup workbook, note, or label | Human-maintained setup context such as wiring, cooldown, sample, channel, station, or selected-ID notes. | Important facts may be semi-structured or manual, not clean machine contracts. |
| Generated setup companion | Derived chip, line, pulse, readout, or runtime-facing file produced from setup or parameter inputs. | Generated files may be useful evidence without being authoritative source truth. |
| Code folder or helper module | Editable experiment code, copied folders, private helper imports, backups, checkpoints, or local variants. | Code identity and runnable readiness are separate concerns. |
| Environment file or local service assumption | `pyproject`, lockfiles, local paths, driver packages, services, and machine-specific runtime state. | Runtime readiness cannot be inferred from file presence alone. |
| Live plot or inspection surface | Existing live graphing, plotting, or notebook view used while a measurement runs. | Running review can start by observing, not controlling, execution. |
| Fit result or analysis output | Arrays, plots, reports, notebooks, fitted values, and workbooks produced after acquisition. | Derived artifacts need lineage and role clarity before handoff or reuse. |
| Copied folder, zip, or shared bundle | Ad hoc transfer unit used to move selected data and context between computers or collaborators. | Portable output needs explicit contents, missing-context reporting, and safe paths. |
| Manual decision or note | Human choice to accept, stop, retry, refit, continue, copy, or share work. | Scopecat should record decisions without turning them into automatic authority. |

## Core Scopecat Domain Concepts

These concepts are introduced by Scopecat but are close to the durable user
problem. They should be modeled explicitly while avoiding final public schema
or SDK commitments.

| Concept | Status | Introduced To | Boundary Notes |
| --- | --- | --- | --- |
| Measurement Record | Accepted transition boundary | Give legacy or external measurement work a local Scopecat identity, source posture, primary data, references, and review visibility. | Not a claim that the legacy system already has this object; does not own execution or scientific validity. |
| Normalized Primary Data | Core transition concept | Make selected measurement rows inspectable, importable, packageable, and testable without parsing arbitrary legacy files. | Separate from raw legacy datasets and derived artifacts. |
| Source Reference | Core transition concept | Preserve where a fact, file, run, or package member came from without importing or interpreting it automatically. | Reference-only by default. Observation or import requires a narrower boundary. |
| Context Link | Core transition concept | Attach parameter, setup, code, environment, artifact, or note evidence to a measurement, package, calibration step, or review. | Linkage does not imply payload ownership, recursive traversal, or shared context schema. |
| Handoff Package | Accepted transition boundary | Replace ad hoc copied folders with explicit package contents and open-before-import review. | Packages are analysis/review artifacts for selected measurement data and declared package members, not offline execution migration, environment restore, or shared lab storage. |
| Parameter State Record | Candidate transition concept | Preserve reviewed point-in-time parameter facts independent of active legacy files when a real entrypoint earns the boundary. | No active implementation owner; does not apply hardware state or own final parameter schema. |

## Process And Integration Objects

These objects are common in workflow-heavy brownfield software. They belong in
the domain model as process vocabulary, not as core domain entities.

| Concept | Role | Introduced To | Boundary Notes |
| --- | --- | --- | --- |
| Review Summary | Process object | Present local findings, readiness, missing context, or blocked state for a human decision. | Review text or JSON is not durable authority unless a boundary says so. |
| Operation Result | Process object | Report the outcome of one command, observation, write, import, package, or review operation. | May be transient or durable. A result is not automatically a domain object. |
| Durable Audit Record | Process object | Persist a narrow fact that an accepted operation, observation, import, write, or user decision occurred. | Use only when durable audit value is real; do not treat every operation result as an audit record. |
| Import Plan | Integration object | Let a receiver preview what could be imported before storage mutation. | Non-mutating by default; durable import needs explicit acceptance and delegated storage rules. |
| Operator Acknowledgement | Process object | Capture user acceptance, deferral, note, or continuation choice without claiming run permission. | Should not become an approval bureaucracy or hardware-safety gate by default. |
| Environment Operation Evidence | Supporting transition concept | Review bounded local manager-operation intent/result facts when a named workflow earns the boundary. | Historical evidence only; does not prove runnable readiness. |
| Calibration Continuation State | Supporting transition concept | Preserve fit review, proposed writes, blocked downstream work, and continuation decisions. | Should remain grounded in failed-fit and manual-continuation entrypoints, not an invented scheduler. |
| Reference Comparison Finding | Supporting transition concept | Compare declared facts against a selected reference without explaining causes. | Does not claim setup truth, reproducibility, or user judgment. |

## Artifact Descriptor Objects

These objects describe artifacts or storage structures. They should not be
confused with operation results or durable audit records.

| Concept | Role | Introduced To | Boundary Notes |
| --- | --- | --- | --- |
| Manifest | Artifact descriptor | Describe identity, members, structure, or declared facts for a storage record, package, or artifact set. | Should not be called a receipt; it describes an artifact rather than proving an operation happened. |
| Package Member | Artifact descriptor | Identify one file or payload carried by a package. | Package-relative identity is separate from source path, storage path, and source authority. |
| Storage Record Member | Artifact descriptor | Identify one file, manifest, projection, or audit record under a Scopecat-owned storage boundary. | Does not define final storage schema by itself. |
| Attachment Or Artifact Reference | Artifact descriptor | Keep arbitrary linked files or analysis results visible without turning them into primary measurement data. | Listing, relation, availability, or handoff visibility does not imply default plotting, payload import, backup, or conversion. |
| Previewable Data Item | Artifact descriptor | Represent normalized primary data or analysis output that declares enough roles, axes, units, components, and shape metadata for conservative preview. | Complex, ragged, trace, vector, and matrix cases remain future preview-model work until accepted by decision or prototype boundary. |

## Modeling Rules

- Name the brownfield object first, then the Scopecat transition concept.
- Keep core domain concepts, process/integration objects, and artifact
  descriptor objects in separate sections.
- Treat `Measurement Record`, `Handoff Package`, `Import Plan`,
  `Context Link`, `Operation Result`, `Durable Audit Record`, and `Manifest`
  as Scopecat-introduced terms, not brownfield-native vocabulary.
- Do not promote a fixture field into domain vocabulary unless it maps to a
  brownfield object or a named transition boundary.
- Classify operation outputs before using them architecturally: many are
  operation results, durable audit records, review summaries, or artifact
  descriptors rather than domain concepts.
- Keep source, storage, package, and external references distinct.
- Treat review, acceptance, import, and mutation as separate concepts.
- Keep context families separate until two or more accepted boundaries need
  the same behavior with the same failure semantics.

## Non-Claims

This model does not accept:

- final Measurement Record storage schema;
- public package schema;
- public SDK object model;
- universal experiment context or shared relation graph;
- automatic data-shape inference or a final plotting model;
- analysis provenance DAG;
- hardware/run execution model;
- scheduler, retry, or rollback model;
- trust, authenticity, or scientific-validity model.

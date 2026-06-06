# ADR-0002: Import Source Anti-Corruption Boundary

## Status

ADR status: accepted.

This ADR records the durable source/reference anti-corruption decision for
legacy import and source handling. Later durable Measurement Records import
work supersedes the historical copy-acceptance slice for active new-record
import, but it does not supersede this anti-corruption boundary.

## Context

Scopecat is being introduced into brownfield lab workflows where useful
measurement facts already exist in legacy systems, notebooks, local folders,
ad hoc exports, generated companions, and user-managed analysis artifacts.

Those sources are valuable, but they are not Scopecat product objects. Legacy
paths can contain implicit semantics, stale state, machine-local assumptions,
private helper code, copied variants, and scientific context that Scopecat
cannot safely infer by scanning files.

Scopecat therefore needs a boundary that can preserve source identity and
accept reviewed normalized data without making core code responsible for
arbitrary legacy parsing, repair, backup, trust, authenticity, scientific
validity, or final storage schema decisions.

## Decision

Scopecat separates these concepts:

| Concept | Accepted meaning | Not implied |
| --- | --- | --- |
| Legacy source | Original or lab-managed data, files, folders, notebooks, or system IDs outside Scopecat storage. | Core parsing, product identity, previewability, repair, backup, or ownership of the legacy system. |
| Source reference | A declared pointer to where a fact, file, run, or artifact came from. | Data-level read, plot readiness, source availability, or payload import. |
| Adapter-normalized primary data | Reviewed data produced or declared in a Scopecat-understood shape. | Stable adapter API, raw legacy support, inferred schema, or universal dataframe behavior. |
| Linked context reference | A declared related parameter, setup, code, environment, artifact, note, or external object. | Recursive traversal, payload import, shared context schema, or display semantics. |
| File-level observation | Availability, digest, byte size, and similar file facts for one explicit source reference. | Row count, schema validation, old-content restore, trust, or scientific validation. |
| Data-level observation | A read using an explicitly supported normalized data model. | Automatic support for arbitrary CSV, HDF5, LabRAD, DataVault, Labber, ndarray, notebook, or matrix formats. |

Scopecat core must not parse arbitrary legacy systems by default. Legacy-
specific knowledge belongs in user-owned or lab-owned adapters unless a later
accepted decision promotes a specific reader into Scopecat.

Scopecat may record references to legacy files, attachments, and artifacts.
It may preview, package, copy, or expose primary data only when a route owns a
supported normalized data model or an explicit adapter authority for that data.

Reference-only import and source observation are review postures. They preserve
declared source facts and optionally make drift visible; they do not mutate
storage, prove trust, guarantee availability, or create restore authority.

## Consequences

- Import and handoff flows must preserve source identity without letting
  legacy file layout become the product domain model.
- Routes that need primary-data preview or packageable bytes must consume
  normalized data or a Measurement Records-owned projection, not raw legacy
  paths.
- File observation can report declared file facts, but it cannot promote a
  reference into parseable data or backup evidence.
- Adapter output boundaries can be tested with file-shaped fixtures, but the
  final adapter transport remains a separate decision.
- Shared measurement-domain models should remain deferred until multiple
  production verticals need the same lifecycle and failure semantics.

## Non-Claims

This ADR does not accept:

- a stable public import API or adapter API;
- core readers for LabRAD, DataVault, Labber, notebooks, HDF5, or lab-specific
  formats;
- final Measurement Record storage schema or indexing;
- existing-record update, repair, moved-reference discovery, or automatic path
  search;
- linked-context payload import or recursive relation traversal;
- GUI import/review workflows;
- package format, package trust model, or durable handoff import behavior;
- dataframe, plotting, broad schema inference, or automatic scan-shape
  semantics;
- backup, restore, shared-storage, snapshot, or watcher authority.

## Current Owners

Use the current owner documents for active details:

- Measurement Records storage, adoption/import, open-by-id, references,
  read models, and handoff projection:
  [`../engineering/prototype-boundaries/measurement-records-storage.md`](../engineering/prototype-boundaries/measurement-records-storage.md)
- Handoff durable import adapter boundary:
  [`../engineering/prototype-boundaries/handoff-durable-import-storage.md`](../engineering/prototype-boundaries/handoff-durable-import-storage.md)
- Handoff package writing, opening, and package review boundaries:
  [`../engineering/prototype-boundaries/handoff.md`](../engineering/prototype-boundaries/handoff.md)
- Canonical journey/use-case ownership:
  [`../product/target-journeys.md`](../product/target-journeys.md)
- Validation evidence:
  [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md)

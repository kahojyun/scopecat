# Package Purpose Boundary

## Status

Discovery boundary note.

This note separates three related ways Scopecat may help users analyze,
share, or move experiment work. It does not accept a final package format,
storage backend, shared filesystem policy, migration workflow, restore
contract, environment schema, execution runner, archive format, signature
model, or GUI contract.

## Purpose Classes

In short:

- **Analysis/review packages** carry selected measurement data for inspection.
- **Shared lab references** point to externally managed lab locations such as
  NAS paths.
- **Offline execution migration** is a future artifact or workflow for moving
  code, environment, settings, and run context to another measurement computer.

| Purpose | Current posture | What is portable | What remains a reference | Not claimed |
| --- | --- | --- | --- | --- |
| Analysis/review package | Current handoff route. Open package, inspect selected measurement data, preview metadata, plot/table facts, findings, and reference-only linked context. | Package directory, `package-manifest.json`, package-local primary measurement data, declared preview metadata, and any package members explicitly written by a validated package slice. | Code context, environment context, linked-context payloads, external source identity, local receipts, local inspection artifacts, and original lab paths unless a future slice promotes a specific payload. | Code restore, environment restore, dependency sync, execution, runnable readiness, recursive linked-context import, or migration completeness. |
| Shared lab reference | Current external-reference and source-identity pressure. A lab-managed path, NAS, shared drive, external repository, or original-system reference remains externally managed and referenceable elsewhere. | Nothing by default; a later export or package slice may materialize selected normalized primary measurement data or a separately validated payload category into a package. | The shared location and observed file facts such as existence, size, checksum, mtime, identity, or access findings where a slice validates observation. | Portability, immutability, availability from every machine, path equivalence, automatic repair, backup, restore, runnable readiness, or packaging authority from observed file facts alone. |
| Offline execution migration | Future route. A stronger artifact or workflow intended to carry or reconstruct enough execution context to continue or rerun work on another measurement computer. | Only future validated payloads such as Scopecat-managed code content, managed workspace archives, environment manifests or locks, dependency artifacts, future Scopecat-owned settings, parameter/setup context, or runner inputs. | User-managed code, user-managed environments, external systems, and shared lab storage may still be referenced when Scopecat does not own or cannot package them. | Current handoff packages do not claim this; reproduction also requires compatibility, restore, execution, hardware, and user-domain checks not yet validated. |

## Current Decision

Current handoff packages are **analysis/review packages**. They are useful when
the receiving user wants to inspect selected measurement data, preview plots or
tables, keep visible findings, and optionally accept reviewed primary data into
local storage.

They are not offline execution migration artifacts. Measurement data
portability for analysis is a different problem from moving the code,
environment, settings, and run context needed to continue experiment execution
on another measurement computer. Reference-only linked context is intentional:
it lets users see that code, environment, attachments, or external source
records exist without pretending the package can restore them or run them.

Shared lab references are also not offline execution migration artifacts. A
NAS or shared drive can make the same data, code, or environment files visible
from multiple lab computers without a Scopecat remote service, but that is a
live external-reference deployment posture, not a carried artifact. It has its
own risks: permissions, mount paths, stale reads, concurrent mutation, missing
network availability, and machine-specific runtime differences.

## Migration Responsibility By Ownership

Migration responsibility follows ownership:

| Surface | Early responsibility | Future Scopecat responsibility |
| --- | --- | --- |
| User-managed experiment code | User migrates with Git, copied folders, shared storage, or lab procedure. Scopecat records references, selected context, and review findings only. | If Scopecat manages code versions, it must validate how managed code content, archives, or workspace materialization move offline. |
| User-managed environment | User migrates with `uv`, Pixi, Conda, copied lockfiles, lab images, or lab procedure. Scopecat records declared environment context and operation review facts only. | If Scopecat manages environment restoration or sync, it must validate manager-specific restore/sync/probe behavior separately. |
| Scopecat settings and route-local configuration | Potential export/import candidate, separate from measurement data handoff and code/environment migration. | If a future slice defines Scopecat-owned settings or route-local configuration, export/import can become an offline portability candidate, but must avoid treating machine-local paths as portable truth. |
| Measurement data for analysis | Current handoff route packages selected normalized primary data and preview metadata. | Stays analysis/review unless a future execution workflow explicitly needs measurement data coupled with execution migration. |
| Parameter/setup/station/run context | Currently selected or reviewed as local context records, not a universal restore model. | May become migration input only after each family earns restorable semantics and hardware boundaries. |

## Design Rule

Before adding package behavior, name the package purpose:

- **Analysis/review**: copy enough selected measurement data and preview
  metadata for inspection; keep linked context reference-only unless a concrete
  reader workflow needs one payload category.
- **Shared lab reference**: preserve identity and optional observed file facts
  for externally managed locations; do not claim portability or old-content
  restore unless content was copied, snapshotted, or archived.
- **Execution migration**: require a new authority boundary for each carried or
  restorable execution-context family: Scopecat-managed code, environment,
  settings, parameters, setup, hardware, execution, and compatibility checks.

Do not let "package experiment context" mean all three purposes at once.
Reference-only experiment context package projection belongs to the
analysis/review package route unless a future slice explicitly changes the
purpose. If the user manages code and environment outside Scopecat, Scopecat
should not claim offline migration for those surfaces; it can only carry
references, observations, settings it owns, and separately validated context
records.

## Relationship To Existing Routes

- Handoff package route owns the current analysis/review package behavior for
  selected measurement data and preview.
- Measurement data reference boundary owns the distinction between normalized
  primary data, external source references, attachments/artifacts, and
  previewable data items.
- Storage-transition export pressure introduced lab-managed network references
  and package materialization vocabulary, but did not accept backup, restore,
  importer, or storage architecture.
- Experiment-code route may contribute code context or managed code version
  references to analysis/review packages. Once Scopecat manages code content,
  offline execution migration becomes a separate artifact, workflow, or
  restore boundary.
- Environment-operation route may contribute declared environment or operation
  review references to analysis/review packages. Environment migration remains
  separate from operation review until restore, sync, runtime probing, and
  manager-specific behavior are validated.

## Future Validation Triggers

Validate offline execution migration only when a concrete user workflow needs
one of these stronger claims:

- continue or rerun experiment workflow on another measurement computer without
  access to the original local workspace;
- export and import future Scopecat-owned settings or route-local
  configuration;
- restore a selected code workspace from carried content;
- reconstruct or sync a declared environment on a receiving machine;
- preserve parameter/setup/station context as restorable run inputs;
- prove a receiver can execute a selected entrypoint under bounded runtime
  conditions;
- distinguish reproduced results from merely inspectable or reviewable data.

Until then, keep current package work analysis/review oriented, keep shared lab
storage as explicit reference posture, and keep user-managed code/environment
migration outside Scopecat's claims.

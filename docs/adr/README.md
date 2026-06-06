# Architecture Decision Records

## Status

ADR navigation and governance.

## Purpose

Provide one flat entry point for Scopecat architecture decisions. This
directory owns the ADR register, the ADR template, and the rules for deciding
what prototype-stage work is formal enough to become an ADR.

Scopecat is still a prototype. Most brownfield pain-point evidence, product
journey posture, migration sequencing, validation findings, and implementation
checklists should stay in their source documents. Create an ADR only when a
prototype result or branch accepts, rejects, defers, supersedes, or retires an
architecture boundary that future work must obey.

Use [`register.md`](register.md) as the current index. Use
[`template.md`](template.md) when creating a new ADR.

ADR files live directly in this directory as `ADR-0001-short-title.md` files.
Do not create type-specific subdirectories.

## Admission Signals

Create or update an ADR when a branch changes a durable architecture boundary,
including:

- import, export, storage, package, or artifact authority;
- execution, runtime, scheduling, hardware control, write-back, or service
  lifecycle authority;
- adapter, anti-corruption, trust, authenticity, redaction, public/export, or
  compatibility boundaries;
- shared model, schema, relation, package format, or cross-module ownership
  boundaries;
- prototype promotion or explicit deferral that affects multiple future
  documents, modules, fixtures, tests, or generated outputs.

Do not create an ADR for:

- product journey cataloging or deferred umbrella journeys;
- migration roadmap order that does not set an architecture boundary;
- discovery/research findings without an accepted boundary;
- prototype notes that only describe current implementation state;
- task lists, hardening inventories, PR scope, or branch plans.

## Prototype Rule

Prototype work can create an ADR only when it promotes or defers a boundary
that future work must obey. Otherwise keep the evidence in prototype-boundary,
workflow-validation, product, brownfield, issue, PR, or owner-local evidence
documents.

## Update Rule

Update the register when a branch creates, supersedes, retires, renumbers, or
materially changes an ADR. Retain historical ADRs unless they were never valid
architecture decisions; use supersession instead of rewriting history when a
valid decision becomes obsolete.

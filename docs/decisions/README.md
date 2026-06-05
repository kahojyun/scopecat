# Decisions

## Status

Decision-record navigation and governance.

## Purpose

Provide one flat entry point for durable Scopecat decisions. This directory
owns the decision register, the template for new decision records, and the rules
for deciding what deserves a durable decision record.

Use this directory when a change needs to answer whether a decision is durable,
what future work must obey, whether the decision is accepted, superseded,
retired, or only proposed, and what should trigger future review.

Use [`register.md`](register.md) as the current index. Use
[`template.md`](template.md) when creating a new decision record.

Registered decision records live directly in this directory as
`DEC-*-short-title.md` files. Do not create type-specific subdirectories such
as `architecture/`, `product/`, or `engineering/`. Do not assign a `DEC-*` ID to
a decision that only lives inside another source document.

## Admission Signals

Create or update a decision record when a branch accepts, rejects, defers,
supersedes, or retires a durable boundary that future work must obey. Common
signals include:

- product scope, target journey, adoption scope, or non-goal boundaries;
- authority boundaries for import, export, storage, execution, runtime,
  scheduling, hardware control, write-back, or service lifecycle;
- artifact, package, public/export, redaction, compatibility, or trust
  boundaries;
- shared model, schema, adapter, integration, or ownership boundaries;
- prototype promotion or explicit deferral that affects multiple future
  documents, modules, fixtures, tests, or generated outputs.

ADR means Architecture Decision Record. Use `ADR` only when a decision changes
architecture-affecting boundaries such as system ownership, storage, package,
artifact, adapter, trust, runtime, execution, or shared model behavior. Do not
use ADR as a required category for every decision record.

## Lightweight Rule

Not every choice needs a new file or a `DEC-*` ID. If a decision is local to one
discovery track, prototype boundary, product map, module README, issue, or PR,
keep it in that source document without registering it here. Create and register a
standalone decision record when multiple future sources need the decision or when
supersession history matters.

## Granularity Rule

Create or promote a `DEC-*` entry only when a branch accepts, rejects,
supersedes, or defers a durable boundary that future work must obey.

Prefer updating the active source document instead of creating a new decision when the
change only records:

- implementation sequencing, PR scope, or current milestone planning;
- validation status, next validation questions, or open advancement options;
- hardening checklists, review findings, or retry/error case inventory;
- wording clarification that does not change the accepted contract;
- source-local implementation detail already owned by a prototype-boundary or
  module README.

Roadmap and "what next" content belongs in the workflow validation map, product
capability map, prototype-boundary advancement questions, issues, PRs, or
branch-specific plans. Decision records should keep stable context, accepted
contract, scope, non-goals, consequences, alternatives, supersession, review
triggers, and related evidence.

## Update Rule

Update the register when a branch creates, supersedes, retires, or materially
changes a durable decision. Do not use this directory for task lists, open
questions without a decision, or validation evidence.

Keep the register as a compact index. During documentation cleanup, retire,
supersede, or move any remaining live guidance into the relevant source
document instead of adding summary columns or preserving decisions that no
longer guide future work.

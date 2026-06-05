# DEC-009: Retire Historical Handoff Discovery Route Decision

## Status

Decision type: discovery.

Decision status: retired.

Date: not recorded.

## Context

A historical handoff discovery route decision previously existed as active
guidance. Later handoff direction moved into current product journeys,
workflow-validation rows, prototype-boundary documents, implementation module
docs, and accepted package/import decision records.

## Decision

Retire the historical handoff discovery route decision as active guidance. Git
history preserves the retired discovery note; current work should follow the
active handoff decisions and current source documents instead.

## Scope

This decision applies to:

- historical handoff discovery guidance;
- register navigation for the retired `DEC-009` handle.

This decision does not apply to:

- current handoff package format, trust, linked-context payload, batch planning,
  archive, or durable-import decisions;
- current handoff implementation and prototype-boundary documents.

## Consequences

Readers have a stable retired decision handle without preserving obsolete
handoff discovery guidance as active direction.

## Alternatives Considered

- Option: keep the historical discovery route decision active. Rejected because
  current handoff direction is now owned by narrower active documents and
  decision records.

## Supersession

Supersedes:

- the historical handoff discovery route decision preserved in Git history.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- the retired historical handoff route needs to be restored as current
  guidance, rather than cited as background evidence.

## Related Evidence

- [`../engineering/prototype-boundaries/handoff.md`](../engineering/prototype-boundaries/handoff.md)
- [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md)

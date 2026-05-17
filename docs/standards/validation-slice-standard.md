# Validation Slice Standard

## Status

Draft process standard after removing the old candidate model.

## Purpose

Define the lightweight process for turning evidence into a small validation
slice without creating a ranked backlog, route-shaped requirement, or prototype
before the user situation is clear.

This document owns process only. It is not a product plan, opportunity map,
architecture decision, fixture contract, or implementation checklist.

## Core Rule

Start from evidence and a concrete user situation. Add artifacts only when they
answer the next real decision.

```text
evidence
  -> opportunity pressure
  -> scenario or JTBD
  -> validation question
  -> fixture, interview, or prototype
  -> decision or contract only when earned
```

An opportunity pressure is not a slice. A pain row is not a slice. A fixture is
not user validation. A prototype is disposable unless its boundary is accepted
by a later decision.

## Minimum Slice Record

A promoted validation slice can live in one compact document. It must answer:

- who the user is and what situation triggers the workflow;
- which evidence and pain rows create enough pressure;
- what the user-visible payoff is;
- what behavior the user or lab must change;
- what fixture, interview, or prototype will test it;
- what Scopecat must not touch;
- what result would make the slice accepted, revised, or deleted.

If non-public source detail supports the slice, the committed record should
preserve only a public-safe source family, validation fact, and redaction note.
Do not publish exact private paths, usernames, machine names, instrument
identifiers, lab labels, sample labels, or source-derived location details.

## Status Language

Use statuses on specific claims, scenarios, fixtures, outputs, and decisions.
Avoid applying one broad status to a folder or route.

| Status | Use when | Does not mean |
| --- | --- | --- |
| Draft | Text exists, but evidence, scope, or acceptance is unstable. | Ready for implementation. |
| Ready | Coherent enough to guide the next analysis or design step. | Fixture, user, or product validation exists. |
| Fixture validated | Synthetic or redacted fixture checks pass. | Users can complete the task better. |
| User validated | Representative users complete the target task and interpret output correctly. | Broad product direction is accepted. |
| Accepted boundary | The project accepts a scoped product, domain, or architecture boundary until reopening criteria fire. | Product-market fit or broad subsystem acceptance. |
| Product accepted | Enough user and product evidence exists to treat the route as product direction. | Future scope can skip decision gates. |
| Provisional | Evidence pressure is explicit but not accepted as a durable route, contract, or decision. | Accepted boundary. |
| Deferred | Scope is intentionally postponed and needs later evidence. | Rejected forever. |
| Superseded | A newer owner doc or decision replaces this artifact for future work. | The old artifact should be rewritten as if it never existed. |

Tracker and index labels are navigation metadata, not validation statuses.

## Fixture And Prototype Rules

Fixtures should be created only after the scenario question is specific enough
to critique. Keep fixtures small, explicit, public-safe, and easy to delete.

Prototype code should be even more disposable than fixture data. Build it when
it tests a user-visible boundary faster than prose can. Delete or replace it
when it starts encoding premature schema, UX, storage, redaction, or workflow
contracts.

## Decision Gates

Open a narrower decision or future architecture ADR only when a validation
slice or implementation depends on one of these boundaries:

- hardware control, device apply, parameter write-back, rollback, or mutation;
- runtime ownership, scheduling, retry, resume, stop behavior, or resource
  locking;
- storage, synchronization, central service, shared-storage semantics, or
  cross-machine authority;
- public output, redaction policy, or recipient-specific disclosure behavior;
- stable API, schema, manifest, vocabulary, or compatibility contract;
- AI-generated advice, proposals, or automated action.

Until a decision exists, preserve the pressure as evidence, scenario text, or
fixture notes rather than implementation scope.

# Research

## Status

Stable research workspace policy.

## Purpose

This directory owns raw or semi-processed research inputs: external
references, interview-to-architecture mapping, legacy pain-point analysis, and
technical spike notes.

Research documents may be messy while active. Durable conclusions should be
promoted along the current docs model:

```text
Evidence -> User Journey -> Pain Point -> Product Capability
  -> Domain Concept -> Architecture Contract -> Subsystem Spec
```

Use the narrowest durable destination that exists or is justified by real
content, such as `product/`, `journeys/`, `architecture/`, `capabilities/`,
`concepts/`, `decisions/`, or future `user/` docs. Do not create placeholder
directories just to match this taxonomy.

Raw research is input, not reusable default context. If a research note becomes
important for future AI sessions, distill it into a compact index, summary, or
decision before treating it as guidance.

## Reference Materials

- `greenfield-experimental-automation-architecture-notes.md` captures the
  initial greenfield architecture discussion for a progressively adoptable
  experimental automation platform. Treat it as raw research input; accepted
  structure and ownership rules require promotion into narrower durable docs.

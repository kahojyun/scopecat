# Repository Agent Instructions

- Follow narrower `AGENTS.md` files when working under their directories.
- When behavior or documented contracts change, update the affected docs,
  implementation, fixtures, tests, and expected outputs together. Before fixing
  review feedback, classify whether it changes contract, implementation, or
  wording.
- Fixtures should be small, explicit, and public-safe by default. Required input
  fields must appear in the fixture or test case, not be silently supplied by
  helpers.
- When changing public output, sharing boundaries, fixtures, or generated
  artifacts, audit identifiers, labels, relation targets, metadata,
  Markdown/JSON output, and payload/code-derived text.
- Keep prototypes within their stated boundary; static-analysis prototypes must
  not execute analyzed fixture or source code.
- Do not generalize architecture, ownership, or reusable contracts from one
  validation slice unless an accepted decision states that scope.

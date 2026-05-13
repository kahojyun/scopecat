# Repository Agent Instructions

- Follow narrower `AGENTS.md` files when working under their directories.
- Treat docs, prototypes, fixtures, and tests as one contract surface. When a
  behavior or boundary changes, update the owning docs, implementation,
  fixtures, tests, and expected outputs together.
- Before fixing review findings, identify whether the finding changes a
  contract, an implementation detail, or wording only. Contract changes require
  linked updates across all affected surfaces.
- Do not let test helpers silently create fields that the documented input
  contract requires explicitly. Required manifest or input fields should be
  visible in the fixture or test case.
- For public-output, sharing-boundary, or redaction changes, check artifact
  IDs, bundle IDs, labels, statuses, relation targets, metadata, Markdown
  output, JSON output, payload-derived text, and code-text-derived text.
- Keep committed fixtures public-safe unless an owning document explicitly
  permits an internal-only fixture. Do not include real local paths, usernames,
  hardware identifiers, instrument addresses, sample identifiers, or
  calibration values in public fixtures.
- Prefer small explicit fixtures over broad copied examples. If full-fidelity
  analysis is needed, keep it outside public fixtures and document only the
  redacted role, relation, ambiguity, and validation purpose.
- Keep prototypes within their accepted decision boundary. If the boundary is
  static analysis, do not execute fixture or source code.
- After a semantic contract change, rerun the relevant tests and perform a
  contract-surface self-check before treating the review finding as fixed.
- Do not promote broad architecture, capability ownership, or reusable
  contracts from a single journey unless an implementation decision or explicit
  project decision requires it.

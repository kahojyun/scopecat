# Development Context

This project is currently developed by one person in a self-review-only workflow, so large changes and breaking changes are acceptable; this describes the development process, not expected deployment scale or data volume.

Until the core workflows are demonstrably easier than ad hoc scripts and small internal scan frameworks, prioritize first-use usability and end-to-end product value over architectural completeness, generalized safety or recovery mechanisms, and additional edge-case coverage.

When a change improves the codebase direction, prefer making the breaking change decisively and updating the affected code in the same pass. Use tests and type checks to identify everything that must be synchronized, rather than accumulating compatibility layers or historical debt.

This is an early, closed implementation, so prioritize product functionality over defensive engineering. Trust static checks, typed internal APIs, and normal Python conventions: do not add runtime type guards, duplicate invariant checks, fallback paths, compatibility shims, or exhaustive tests for hypothetical misuse unless data crosses an untrusted boundary or a concrete failure demonstrates the need. Code review should focus on intended-path correctness, clear types, and product value.

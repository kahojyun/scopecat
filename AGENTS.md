# Development Context

This project is currently developed by a single person in a purely local workflow. There are no external consumers or historical compatibility contracts that need to be preserved.

When a change improves the codebase direction, prefer making the breaking change decisively and updating the affected code in the same pass. Use tests and type checks to identify everything that must be synchronized, rather than accumulating compatibility layers or historical debt.

This is an early, closed implementation, so prioritize product functionality over defensive engineering. Trust static checks, typed internal APIs, and normal Python conventions: do not add runtime type guards, duplicate invariant checks, fallback paths, compatibility shims, or exhaustive tests for hypothetical misuse unless data crosses an untrusted boundary or a concrete failure demonstrates the need. Code review should focus on intended-path correctness, clear types, and product value.

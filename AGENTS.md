# Development Context

This project is currently developed by a single person in a purely local workflow. There are no external consumers or historical compatibility contracts that need to be preserved.

When a change improves the codebase direction, prefer making the breaking change decisively and updating the affected code in the same pass. Use tests and type checks to identify everything that must be synchronized, rather than accumulating compatibility layers or historical debt.

## Validation Boundaries

Treat frozen transient IR created by project constructors as trusted internal
state. Establish invariants once at construction or when independently
produced artifacts are bound, then rely on types, immutability, and tests.
Do not add construction secrets, self-fingerprints, or repeated whole-object
validation solely to defend against same-process mutation of internal values.

Keep runtime validation at authoring/configuration ingress, provider and effect
boundaries, durable storage and recovery boundaries, and plugin or adapter
interfaces. Cover interchangeable adapters and repositories with shared
contract tests.

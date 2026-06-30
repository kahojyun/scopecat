# Development Context

This project is currently developed by a single person in a purely local workflow. There are no external consumers or historical compatibility contracts that need to be preserved.

When a change improves the codebase direction, prefer making the breaking change decisively and updating the affected code in the same pass. Use tests and type checks to identify everything that must be synchronized, rather than accumulating compatibility layers or historical debt.

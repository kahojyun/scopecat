# Handoff Prototype Module

Engineering prototype module for read-only Scopecat-authored handoff package
use.

This module is route-local prototype code. It tests a production-shaped Python
entrypoint over validated handoff discovery candidates without accepting final
public SDK names, package format, storage import behavior, GUI architecture,
plotting stack, or shared measurement-record domain model.

The runtime API exposes route-local objects rather than discovery candidate
summary dictionaries. `as_open_summary()` exists as a copy-safe prototype
snapshot, not as a public contract.

The prototype owns its handoff-specific manifest preview and contract helpers
inside this module. Discovery implementation candidates remain historical
validation inputs, not runtime dependencies for this route.

Raw manifest dictionaries are validated at the package boundary. After that,
opener internals consume typed route-local manifest fragments and package
projection objects.

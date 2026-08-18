# Development Context

This project is currently developed by one person in a self-review-only
workflow. Large and breaking changes are acceptable when they improve the
codebase direction; update affected code in the same pass instead of adding
compatibility layers. This describes the development process, not expected
deployment scale or data volume.

This is an early, closed implementation. For trusted internal code, rely on
static checks, typed APIs, and normal Python conventions. Add runtime guards,
fallback paths, duplicate invariant checks, or exhaustive edge-case tests only
at untrusted boundaries or in response to concrete failures. Review primarily
for intended-path correctness and clear types.

# Managed Code Version Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It holds a production-shaped experiment for the first managed code-version
record slice:

- build a structured managed-code-version summary from explicit fixture input;
- keep the builder side-effect free;
- validate that managed-version file records match a captured code-version
  candidate include list;
- record stable identity, file inventory, content-integrity hints, and
  materialization intent;
- avoid reading source files, inspecting Git state, creating archives,
  restoring environments, materializing workspaces, importing code, executing
  code, or defining workflow/DAG contracts;
- keep Markdown review rendering in fixture/test support, not in this package.

The package exists to test whether a captured code-version candidate can be
shaped into a first Scopecat-managed version record without deciding final
storage, restore, sync, environment, loading, execution, merge, GUI, or
workflow semantics.

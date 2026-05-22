# Experiment Code Selection Candidate

This package is an implementation candidate, not accepted Scopecat
architecture.

It holds a production-shaped experiment for the experiment code selection
slice:

- build a structured selected-code summary from explicit fixture input;
- keep the builder side-effect free;
- avoid reading source files, inspecting Git state, scanning unselected
  folders, discovering dependencies, importing code, executing code, restoring
  environments, materializing workspaces, or defining workflow/DAG contracts;
- keep Markdown review rendering in fixture/test support, not in this package.

The package exists to test whether the current fixture-backed selected-code
record boundary can be expressed cleanly as code. It should not be treated as a
final module layout, managed workspace store, Git replacement, environment
manager, runner API, package manager, workflow model, or GUI contract.

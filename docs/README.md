# Scopecat Direction

This directory is intentionally small. It records lasting product direction
that should remain useful as the implementation changes.

- [Project charter](project-charter.md): product goals, principles, and scope
  boundaries.
- [Experiment execution semantics](experiment-execution-model.md): the lasting
  compiler, domain-lowering, effect-safety, and logical-result contract.
- [Lab daemon](lab-daemon.md): durable ownership, admitted execution, and the
  client boundary.
- [Instrument control](instrument-control.md): direct device sessions,
  connection UX, notebook APIs, driver boundaries, and the shared virtual lab.

Keep implementation architecture, package inventories, completed migration
plans, and current interface lists close to the code and tests that own them.
Use focused docstrings when an implementation decision needs local context.

Add another document when lasting product direction is better explained beyond
a specific code boundary.

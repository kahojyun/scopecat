# Scopecat Project Charter

Scopecat is a local-first Python toolkit for running laboratory experiments
with less setup and less repetitive code than ad hoc scripts and small internal
scan frameworks.

It should fit naturally into notebooks and existing Python workflows. Users
should gain useful structure, live visibility, and reusable results without
first adopting a new operational process.

## Current Stage

Scopecat is an early, single-user project. Its current goal is to prove that it
is easier and more useful than the tools researchers already use.

Success currently means:

- a new user can run a virtual experiment quickly;
- direct instrument control remains familiar to Python users;
- common scans require little application code;
- progress, measurements, and failures are easy to inspect;
- results remain available after the notebook finishes;
- moving from exploratory notebook code to a reusable experiment is incremental.

New features and abstractions that do not improve one of these paths should
normally wait.

## Product Direction

Scopecat should help users:

- control instruments and build scans through clear Python APIs;
- organize measurements automatically by run and scan point;
- inspect live progress and completed results from a local GUI;
- reuse experiment definitions without hiding ordinary Python;
- retain enough configuration and context to understand useful results;
- add lab-specific devices and domain logic without changing the core.

## Principles

- Optimize first use and common workflows before rare failure modes.
- Keep ordinary use no more complicated than a small internal scan framework.
- Introduce concepts only when demonstrated workflows require them.
- Hide storage, coordination, and execution machinery from normal user code.
- Make advanced provenance and recovery available progressively.
- Do not silently retry a hardware write when its outcome is unknown.
- Prefer simple models and direct breaking changes while the project is internal.
- Judge architecture by the user workflows it enables, not by theoretical
  completeness.

## Current Non-Goals

- Comprehensive laboratory safety or interlock enforcement.
- Multi-user scheduling or distributed execution.
- General recovery from every interrupted hardware operation.
- Replacing plotting, analysis libraries, notebooks, or all existing drivers.
- A universal representation for every laboratory domain.
- Becoming an ELN, LIMS, data warehouse, or general automation platform.

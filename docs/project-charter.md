# Scopecat Project Charter

Scopecat is a local-first Python platform for research labs that want
experiment workflows to become easier to run, understand, and reproduce
without replacing their existing notebooks, scripts, and instrument code.

## Product Goals

Scopecat should make it practical to:

- describe and validate experiment intent before hardware effects;
- preserve enough configuration, data, analysis, and execution evidence to
  understand and reproduce a run;
- keep consequential configuration changes explicit and reviewable;
- let manual Python workflows grow into reusable experiments incrementally;
- integrate laboratory-specific domain semantics and hardware without coupling
  them to the core platform.

## Principles

- Stay local-first, Python-first, and useful from existing lab workflows.
- Favor explicit, inspectable state over behavior hidden in mutable sessions.
- Preserve provenance between intent, configuration, measurements, analysis,
  and effects where it helps users understand a run.
- Treat uncertain hardware effects honestly; never silently retry when doing so
  may repeat an effect.
- Keep the core domain-neutral and add abstractions only when demonstrated
  workflows need them.
- Prefer simpler models and direct breaking changes while the project remains
  internal and compatibility is not a product requirement.

## Non-Goals

- Replacing existing notebooks, drivers, plotting tools, or analysis scripts.
- Generalizing every domain and backend into one universal representation.
- Requiring centralized infrastructure for first use.
- Becoming a full ELN, LIMS, data warehouse, plotting application, or general
  automation platform.

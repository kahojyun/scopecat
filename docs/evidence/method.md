# Evidence Method

## Status

Evidence interpretation rules.

## Purpose

Keep [`evidence-register.md`](evidence-register.md) focused on stable `EV-*`
claims. This file defines how to read those claims: source coverage, evidence
classes, support strength, and update rules.

## Source Coverage

Treat source families separately:

- predecessor measurement-system lessons are useful but over-emphasize
  measurement history and stable reopen;
- the workflow improvement case adds current friction around notebooks, copied
  code, parameter and registry files, wiring sheets, generated artifacts,
  derived arrays, environment coupling, and report handoff;
- current-owner clarification can narrow intended pains and workarounds, but it
  is not independent user research; it can still justify lab-specific discovery
  when the claim is explicitly scoped to the project owner's lab;
- historical automation discussion is low-confidence design pressure;
- blind persona and capability-gap role-play are prompt-method checks, not user
  research;
- external framework references are baseline context, not proof of Scopecat
  product scope.

Keep these judgments separate:

- whether a claim is well supported by evidence;
- which source families support it;
- whether it should influence product discovery.

## Evidence Classes

| Class | Meaning | Handling |
| --- | --- | --- |
| Observation | Directly observed in extracted notes or code-sample review. | Safe to cite with portability and redaction caveats. |
| Evidence-backed inference | Reasoned conclusion supported by multiple observations. | Candidate for problem framing or narrow promotion. |
| Latent pressure | Plausible pain hidden by the old workflow's limits. | Preserve source coverage; validate before treating as demand. |
| Hypothesis | Plausible product shape, UX, ordering, or API. | Keep out of accepted scope until validation. |
| Future pressure | Likely later capability pressure. | Preserve as background; do not implement from evidence alone. |
| ADR-gated | Mutation, compatibility, storage, distributed, remote, safety, or AI-action risk. | Requires explicit decision before acceptance. |

Support strength is claim-level support only. It does not mean a pain is
urgent, ready for implementation, or high leverage.

## ID Rules

`EV-*` is the only stable evidence ID family. After an evidence ID is
referenced from another document, do not renumber it. Add a new row instead.

Problem framing uses named problem-brief documents in
[`../discovery/problem-briefs/`](../discovery/problem-briefs), not durable pain
IDs.

## Source Handling

- Treat LabRAD, Data Vault numeric IDs, `idx` filenames, latest-file lookups,
  local counters, and local folder conventions as source conventions and
  reference cases, not product concepts.
- Use "companion artifact" as the product-neutral term. "Sidecar" is legacy
  evidence vocabulary.
- Treat notebooks as current-state workflow spines and provenance evidence; do
  not infer automatic notebook-state capture.
- Treat parameter files, registry files, wiring sheets, generated summaries,
  and setup files as opaque context candidates unless a later model owns their
  semantics.
- Treat physical wiring, mounted sample state, chip topology, line attenuation,
  and alias maps as declared or externally evidenced state unless a validation
  path exists.
- Prefer local, versioned, evolvable schemas over a universal parameter or
  setup ontology in early validation work.
- Surface source, provenance, freshness, ambiguity, selected/proposed/applied
  status, and missing facts.

## Updating Evidence

- If a new row changes a problem brief or adoption route, update that
  owner.
- If a source is messy, biased, generated, or historical, preserve the useful
  pressure and label its class instead of either deleting it or over-promoting
  it.
- If a prompt, role-play, or blind review produces a useful idea, tie it to
  source evidence or mark it as latent pressure before it influences scope.
- If a discussion introduces a solution-shaped concept, first recover the
  user-visible pain that made the concept attractive.

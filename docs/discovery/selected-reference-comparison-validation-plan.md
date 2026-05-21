# Selected Reference Comparison Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a first fixture boundary for selected-reference comparison.
It does not accept a final comparison engine, user-judgment engine, setup truth
contract, raw-data comparison, fit-quality comparison, user-provided analysis
conclusion model, or GUI design.

## Source Material

The first fixture should build on already validated discovery pressure:

- selected measurement export for explicit selection and non-recursive context;
- running measurement inspection for declared preview metadata;
- parameter state management for selected parameter-state references;
- setup binding for selected setup-binding and station-registry references;
- the selected-reference problem brief for finding vocabulary and
  user-interpretation boundaries.

Experiment code/version context is also an important selected-reference
comparison dimension because code differences can explain why one run can be
reproduced, inspected, or executed while another cannot. This first fixture
intentionally omits code comparison until the experiment-code-selection slice
defines the minimum code reference boundary.

## Validation Question

Can Scopecat show useful context differences between a current measurement and
a user-selected reference while leaving interpretation to users or
user-provided analysis code?

The first fixture treats the selected reference as coming from an ordinary user
mark on a measurement record. Labels such as last-working, notable, or
best-observed are user-provided context, not special Scopecat semantics.

First fixture:

- `tests/fixtures/selected_reference_comparison/basic_context_compare/`

## Concept Boundary

The first selected-reference boundary should distinguish:

| Concept | Meaning In This Plan |
| --- | --- |
| Current measurement | The measurement the user is inspecting or trying to understand now. |
| Selected reference | A user-chosen comparison anchor, such as last-working, notable, best-observed, or simply relevant. |
| Named input snapshot | Run-start context such as parameter state, setup binding, or station registry reference. |
| Declared preview metadata | Shape and role metadata sufficient to say whether a quick visual comparison is plausible. |
| Comparison finding | A precise finding label: changed, missing, unverified, redacted, unlinked, same-observed, or not-compared. |

The fixture compares declared context. It should not inspect raw data, execute
code, score user judgment, interpret user analysis conclusions, or infer
physical setup truth.

It also should not compare experiment code yet. Adding code-version fields here
would invent a code-reference model before that slice is validated.

## First Fixture Shape

The first fixture should stay small:

- one current measurement;
- one selected reference measurement;
- a reference selected through a generic user mark such as
  `last_working_reference`;
- matching experiment/sample/cooldown labels;
- named input snapshots for parameter state, setup binding, and station
  registry on both sides;
- same-observed setup binding;
- changed parameter state;
- same declared preview metadata;
- quick preview compatibility as future browsing or overlay pressure;
- one missing current fit artifact;
- one unlinked reference analysis note;
- one unverified declared sample fact;
- one redacted station connection fact;

The fixture intentionally excludes experiment code/version references.

## Expected Output

Expected review output should let a reviewer answer:

- why the reference was selected;
- which user mark selected the reference;
- which named input snapshots changed or matched;
- whether declared preview metadata matches;
- whether compatible preview metadata could support quick browsing or overlay;
- what is missing, unlinked, unverified, redacted, same-observed, changed, or
  not compared;
- that findings are context comparison results, not cause attribution.
- that interpretation belongs to users or user-provided analysis code.

## Out Of Scope

This plan does not earn:

- final comparison engine;
- user-judgment engine;
- setup truth;
- automatic cause attribution;
- raw-data or waveform comparison;
- publication-grade plotting;
- fit-quality comparison;
- user-provided analysis conclusion model;
- experiment-code or code-version comparison;
- shared run-context framework;
- GUI design.

## Current Recommendation

Create one fixture and expected output before writing any implementation
candidate. The first goal is to validate the comparison-report boundary and
finding vocabulary, not to build a comparison engine.

# Selected Reference Comparison Validation Plan

## Status

Validation plan, not an ADR.

This plan defines fixture boundaries for selected-reference comparison. It
does not accept a final comparison engine, user-judgment engine, setup truth
contract, raw-data comparison, fit-quality comparison, user-provided analysis
conclusion model, managed code workspace, Git analysis, environment readiness,
code execution, or GUI design.

## Source Material

The fixtures should build on already validated discovery pressure:

- selected measurement export for explicit selection and non-recursive context;
- running measurement inspection for declared preview metadata;
- parameter state management for selected parameter-state references;
- setup binding for selected setup-binding and station-registry references;
- the selected-reference problem brief for finding vocabulary and
  user-interpretation boundaries.

Experiment code context is also an important selected-reference
comparison dimension because code differences can be reviewed as declared
context between a current measurement and a selected reference. The
experiment-code-recording slice defines a minimum recorded-code context shape
that can feed the declared code-context comparison fixture.

## Validation Question

Can Scopecat show useful context differences between a current measurement and
a user-selected reference while leaving interpretation to users or
user-provided analysis code?

The first fixture treats the selected reference as coming from an ordinary user
mark on a measurement record. Labels such as last-working, notable, or
best-observed are user-provided context, not special Scopecat semantics.

Fixtures:

- `tests/fixtures/selected_reference_comparison/basic_context_compare/`
- `tests/fixtures/selected_reference_comparison/code_context_compare/`

## Concept Boundary

The selected-reference fixtures should distinguish:

| Concept | Meaning In This Plan |
| --- | --- |
| Current measurement | The measurement the user is inspecting or trying to understand now. |
| Selected reference | A user-chosen comparison anchor, such as last-working, notable, best-observed, or simply relevant. |
| Named input snapshot | Run-start context such as parameter state, setup binding, or station registry reference. |
| Declared preview metadata | Shape and role metadata sufficient to say whether a quick visual comparison is plausible. |
| Comparison finding | A precise finding label: changed, missing, unverified, redacted, unlinked, same-observed, or not-compared. |
| Code context | Declared root, entrypoint, included files or source observations, notebook recording policy, and declared refs that define a code snapshot scope. The fixture compares recorded instances of this context. |
| Code snapshot record identity | Fixture-local point-in-time code snapshot record ID that can be compared without accepting managed workspace storage or full managed-version comparison. |
| Recorded source observation | Fixture-local token for comparing recorded source observations, not a checksum or integrity contract. |
| Code capture state | Whether a code item is content-captured, reference-only, missing, redacted, or excluded. This controls whether comparison can say changed, same-observed, missing, unverified, redacted, or not-compared. |

The fixtures compare declared context. They should not inspect raw data,
execute code, score user judgment, interpret user analysis conclusions, or infer
physical setup truth.

The code-context fixture compares declared recorded-code context. It should
not inspect internal Git state, scan live files, resolve dependencies, restore
managed workspaces, load selected versions, execute code, or define workflow
contracts.

Future code comparison cases should be added as a fixture family rather than as
one selected-version comparison engine. Start with the comparable surface that
the records expose:

- context comparison for entrypoints, include lists, declared refs, and notebook
  policy;
- capture-state comparison for content-captured, reference-only, missing,
  redacted, or excluded items;
- managed-version inventory comparison only after managed-version records expose
  inventory and integrity hints;
- editable-folder observation only after a slice earns safe current-folder
  observation.

Semantic source diff, Git diff, dependency readiness, environment readiness,
loading, and execution remain separate validation questions.

## First Fixture Shape

The basic fixture should stay small:

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

The basic fixture intentionally excludes experiment code context references.

The code-context fixture should stay small:

- one current measurement;
- one selected reference measurement;
- both measurements reference recorded code context as a named input;
- one matching notebook entrypoint path and recording policy;
- changed recorded-code context and code snapshot record identities;
- one changed entrypoint source observation;
- one same-observed helper source observation;
- one helper missing from current and one helper missing from reference;
- one same-observed declared environment profile hint;
- one redacted external root display value;
- explicit not-compared scope for internal Git state, dependency closure,
  environment readiness, code execution, managed workspace restore, and
  workflow/DAG behavior.

## Expected Output

Expected review output should let a reviewer answer:

- why the reference was selected;
- which user mark selected the reference;
- which named input snapshots changed or matched;
- whether declared preview metadata matches;
- whether compatible preview metadata could support quick browsing or overlay;
- what is missing, unlinked, unverified, redacted, same-observed, changed, or
  not compared;
- what recorded-code context changed, matched, or is missing;
- that findings are context comparison results, not cause attribution;
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
- managed code workspace storage;
- Git analysis;
- dependency discovery;
- environment readiness;
- selected-version loading;
- code execution;
- semantic source diff;
- shared run-context framework;
- GUI design.

## Slice Recommendation

Keep fixtures and expected output ahead of implementation candidates unless a
near-term workflow needs production-shaped code. The goal is to validate the
comparison-report boundary and finding vocabulary, not to build a comparison
engine.

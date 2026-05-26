# Environment Review Bundle Candidate

This candidate composes previously produced environment review summaries for a
manual rerun context.

Summary posture: `review_summary`. The candidate output is a deliberate
projection of selected environment review facts, not a raw dump of the input or
a portable/export artifact.

It can:

- group a selected reference, prepared run context, declared environment
  comparison, environment file observation, and readiness plan;
- validate that all environment inputs point at the same selected current
  environment and prepared-run scope;
- aggregate comparison, file-observation, and readiness findings into one
  review bundle;
- keep review findings separate from dependency resolution, dependency sync,
  package installation, runtime probing, code import, code execution, hardware
  checks, shared environment schema, managed runners, run-blocking decisions,
  and runnable-readiness claims.

Raw JSON fixture input is validated as a slice-local contract, not as a shared
environment schema. The candidate-local `contracts.py` module validates
selected composition facts into dataclass contract records before the summary
builder projects them.
Current composition-specific checks remain local: selected-reference
continuity, prepared-context scope alignment, environment pair alignment,
file-observation and readiness-plan alignment, exact top-level source shape,
exact selected-record shapes, exact finding-row shapes, non-empty scalar
identifiers, labels, and finding basis text, non-negative scalar counts, exact
non-operational claim shape, declaration-only role/status vocabulary, bounded
count-map keys, comparison count-map consistency with comparison finding rows,
readiness review-state count consistency with readiness finding rows, bounded
finding vocabularies, finding boundary vocabularies, and finding source
alignment. All file-observation records derive their projected review-finding
count from projected findings rather than trusting fixture counts; shared
file-observation records aggregate those projected findings. File-observation
classification and status counts may not contradict projected findings.
Component records are selected by bundle reachability; finding rows must all
reference a bundled review bundle; duplicate top-level record identifiers are
still rejected.

## Composition Contract Matrix

The slice keeps its contracts explicit as candidate-local matrices rather than
as a shared environment schema:

- `POLICY_ATTENTION_MATRIX` maps policy fields and accepted values to projected
  attention rows.
- `COMPARISON_FINDING_STATES`, `FILE_OBSERVATION_CLASSIFICATION_FINDINGS`, and
  `READINESS_FINDING_STATES` map finding vocabularies to count states,
  classification families, and projected review states.
- `FILE_FINDING_DOES_NOT_CLAIM` and `READINESS_FINDING_DOES_NOT_CLAIM` keep
  finding boundaries attached to each accepted finding code.
- count-map validators keep aggregate scalar counts, bounded state maps, and
  detailed finding rows in agreement.

This matrix is a review aid for this composition slice only. It should not be
promoted into a reusable environment schema until the same shape is needed by
multiple accepted composition slices.

It does not read files, resolve dependencies, run dependency sync, install,
update, or remove packages, parse dependency or environment files, inspect
interpreters, import code, execute code, contact hardware, define a shared
environment schema, make run-blocking decisions, or decide that a run can
start.

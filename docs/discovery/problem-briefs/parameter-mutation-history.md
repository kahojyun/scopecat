# Parameter Mutation And History

## Status

Evidence-backed problem brief.

## User-Facing Failure

Mutable parameter files and calibration updates make it hard to understand
which parameter state a run used, how parameters drifted, which state should be
retried, and which bad writes should be excluded from later analysis.

## Observed Sample Evidence

- Active parameter files are copied into run-adjacent snapshots.
- Experiment and calibration code directly overwrites parameter JSON.
- Historical analysis reads run-scoped parameter snapshots.
- Setting directories contain active files, backups, dated variants, lock
  clues, generated companion files, and run-number snapshots.
- Local parameter manager code shows snapshot, diff, and reset pressure, but
  does not validate product rollback semantics.

## Project-Owner Clarification

- The primary value is parameter memory: drift/history queries, working-point
  or branch identity, run links, explicit checkpoints, and bad-state exclusion.
- Proposal/review may be useful as an optional higher-safety path, but direct
  update style is common and should not be dismissed.
- Bad states should not be deleted by default. The useful model is closer to
  yank/exclude-from-default-analysis than hard delete.
- User-declared parameter write steps may be part of a local batch or
  calibration workflow. The stronger boundary is Scopecat deciding what to
  mutate, not Scopecat recording or executing an explicit user-authored write.

## Derived Hypotheses

- A small validation question could compare direct updates plus automatic
  checkpoint/diff recording against explicit proposal/review.
- Run-linked parameter history, previews, checkpoints, and declared write-step
  records may be valuable before Scopecat owns automatic mutation decisions.

## Out Of Scope For This Brief

- Universal parameter models, final storage format, Scopecat-decided write-back
  ownership, rollback automation, hard-delete policy, and autonomous
  calibration.
- Treating static files as authoritative live hardware or setup truth.

## Possible Validation Questions

- Can retained history, run links, branch/working-point labels, and bad-state
  exclusion solve the immediate drift/retry pain while making declared writes
  auditable?
- Is proposal/review adopted only in higher-risk paths, or does it need to be
  part of the first parameter-memory experience?

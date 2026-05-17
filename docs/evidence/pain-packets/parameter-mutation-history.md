# Parameter Mutation And History

## Status

Evidence-backed pain packet. Not a storage schema, write-back contract,
permission model, rollback design, or autonomous calibration scope.

## User-Facing Failure

Mutable parameter files and calibration updates make it hard to understand
which parameter state a run used, how parameters drifted, which state should be
retried, and which bad writes should be excluded from later analysis.

## Observed Sample Evidence

- Active parameter files are copied into run-adjacent snapshots.
- Experiment and calibration code directly overwrites parameter JSON.
- Historical analysis reads run-scoped parameter snapshots.
- Setting directories contain active files, backups, dated variants, lock
  clues, generated sidecars, and run-number snapshots.
- Local parameter manager code shows snapshot, diff, and reset pressure, but
  does not validate product rollback semantics.

## Project-Owner Clarification

- The primary value is parameter memory: drift/history queries, working-point
  or branch identity, run links, explicit checkpoints, and bad-state exclusion.
- Proposal/review may be useful as an optional higher-safety path, but direct
  update style is common and should not be dismissed.
- Bad states should not be deleted by default. The useful model is closer to
  yank/exclude-from-default-analysis than hard delete.

## Derived Hypotheses

- A small validation question could compare direct updates plus automatic
  checkpoint/diff recording against explicit proposal/review.
- Run-linked parameter history may be valuable before Scopecat owns any apply
  or mutation path.

## Premature / Do Not Promote Yet

- Universal parameter model, final storage format, permission model, write-back
  ownership, rollback automation, hard-delete policy, or autonomous calibration.
- Treating static files as authoritative live hardware or setup truth.

## Possible Validation Questions

- Can retained history, run links, branch/working-point labels, and bad-state
  exclusion solve the immediate drift/retry pain without Scopecat applying
  parameters?
- Is proposal/review adopted only in higher-risk paths, or does it need to be
  part of the first parameter-memory experience?

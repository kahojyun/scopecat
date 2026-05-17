# Adoption Hypotheses

## Status

Provisional discovery owner.

## Purpose

Name the few user-value directions that are plausible enough to compare, but
not yet accepted as product scope or implementation order.

Each hypothesis should stay phrased as a behavior change to test. Concrete UI,
schema, runner, storage, sync, or service shapes belong in a later validation
or architecture owner only after a smaller question needs them.

Evidence claims live in
[`../evidence/evidence-register.md`](../evidence/evidence-register.md).
Problem framing lives in
[`problem-briefs/README.md`](problem-briefs/README.md).

## Hypotheses

| Hypothesis | Evidence pressure | Question to test |
| --- | --- | --- |
| Select and hand off useful runs | Existing bundle ambiguity, selected-context loss, source identity, portable record movement, and handoff pressure. | Can users select useful runs and move enough context to an analysis computer with less reconstruction than copying folders manually? |
| Choose or migrate experiment code | Copied folders, notebooks, entrypoint ambiguity, dependency readiness, known-good references, and cross-computer code drift. | Can users choose, restore, or migrate the next code version without guessing which copied folder is working? |
| Run and continue calibration work | Scan semantics, grouped calibration intent, review gates, failure policy, continuation, local sequential execution, and outcome records. | Can users run user-authored calibration steps one after another, pause for review, and continue useful work better than with notebook cell queues? |
| Recover parameter state | Mutable parameter files, direct updates, bad states, drift queries, working-point branches, and run links. | Can users recover and compare parameter states without asking Scopecat to apply mutations? |
| Compare against known-good context | False confidence, setup reality, known-good references, scientific comparability, support packages, and control-PC safety. | Can users see changed or missing context against a reference without Scopecat claiming equivalence or setup truth? |
| Recheck analysis handoff impact | Derived arrays, figures, fits, reports, correction choices, exclusions, source runs, and calibration impact. | Can users recheck derived analysis after a handoff, calibration, setup, code, or analysis change without tracing notebooks manually? |

## Shared Constraints

Cross-machine value should first be tested as portable records, export/import,
or handoff. Shared storage may help when a lab already has it, but remote
execution, central services, sync, leases, and resource arbitration are
separate decisions.

Local batch execution may be unattended when the user has declared the steps,
order, review gates, and stop/failure policy. Open-ended autonomy, remote
execution, resource arbitration, automatic mutation, and write-back remain
separate decisions.

Cross-computer code movement should first be tested as explicit selection and
recovery. Publish/pull, automatic sync, Git hosting, deployment management,
and load-selected-version execution remain later hypotheses.

General runtime ownership, managed execution, code registries, automatic
version management, proposal workflows, and similar solution names should stay
out of this file unless a validation result makes them the next question.

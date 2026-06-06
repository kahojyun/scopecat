# Document Map

## Purpose

Flat navigation map for current Scopecat docs. Use [`README.md`](README.md) for
the recommended top-down reading path.

## Map

```text
docs/
  product/   product vision, success metrics, canonical journey/use-case
              index, target capabilities, and adoption modes
  brownfield/ current-state assessment, transition architecture, migration
              strategy, and migration roadmap
  architecture/ initial domain model, context map, and architecture boundaries
  adr/       architecture decision records, register, and template
  engineering/ delivery maturity model, workflow validation map,
               implementation register, and prototype boundaries
  testing/    fixture and expected-output policy
  discovery/  problem briefs and bounded validation guidance
```

| Document | Use For |
| --- | --- |
| [`README.md`](README.md) | Documentation purpose and editing rules. |
| [`AGENTS.md`](AGENTS.md) | AI-session rules for work inside `docs/`. |
| [`product/README.md`](product/README.md) | Product documentation navigation. |
| [`product/vision.md`](product/vision.md) | Product vision and durable product posture. |
| [`product/success-metrics.md`](product/success-metrics.md) | Product success metrics, journey outcome signals, promotion checks, and anti-metrics. |
| [`product/target-journeys.md`](product/target-journeys.md) | Canonical target journey, use case, candidate use case, and supporting workflow index. |
| [`product/target-capabilities.md`](product/target-capabilities.md) | Target product capabilities, maturity, evidence state, and open advancement questions. |
| [`product/adoption-strategy.md`](product/adoption-strategy.md) | Product adoption modes, first user changes, user value, and adoption risks. |
| [`product/managed-experiment-code-posture.md`](product/managed-experiment-code-posture.md) | Product posture and current boundary for managed experiment-code versions. |
| [`brownfield/README.md`](brownfield/README.md) | Brownfield documentation navigation. |
| [`brownfield/current-state-assessment.md`](brownfield/current-state-assessment.md) | As-is lab workflow and artifact patterns. |
| [`brownfield/transition-architecture.md`](brownfield/transition-architecture.md) | Brownfield current pattern, transition posture, Scopecat-owned boundary, and deferred authority map. |
| [`brownfield/migration-strategy.md`](brownfield/migration-strategy.md) | Brownfield modernization strategy, migration patterns, and authority-transfer rules. |
| [`brownfield/migration-roadmap.md`](brownfield/migration-roadmap.md) | Brownfield design-validation sequence and decision gates. |
| [`brownfield/risk-register.md`](brownfield/risk-register.md) | Recurring brownfield risks, mitigation owners, and review triggers. |
| [`architecture/README.md`](architecture/README.md) | Architecture documentation navigation. |
| [`architecture/as-is-architecture.md`](architecture/as-is-architecture.md) | Current lab-system architecture as integration pressure. |
| [`architecture/domain-model.md`](architecture/domain-model.md) | Layered domain vocabulary and modeling rules. |
| [`architecture/context-map.md`](architecture/context-map.md) | Bounded contexts, ownership posture, and anti-corruption relationships. |
| [`architecture/artifact-boundary-and-redaction.md`](architecture/artifact-boundary-and-redaction.md) | Artifact boundary and redaction architecture policy. |
| [`adr/README.md`](adr/README.md) | Architecture decision record navigation and governance. |
| [`adr/register.md`](adr/register.md) | Current architecture decision record index. |
| [`adr/template.md`](adr/template.md) | Template for new architecture decision records. |
| [`engineering/README.md`](engineering/README.md) | Engineering governance navigation for maturity, workflow, capability, and promotion rules. |
| [`engineering/delivery-maturity-model.md`](engineering/delivery-maturity-model.md) | Product objects, maturity states, validation methods, promotion rules, and drift control. |
| [`engineering/workflow-validation-map.md`](engineering/workflow-validation-map.md) | Validation evidence, missing seams, and next validation questions for canonical use cases. |
| [`engineering/implementation-register.md`](engineering/implementation-register.md) | Live implementation owners and primary module or boundary detail docs. |
| [`engineering/terminology.md`](engineering/terminology.md) | Standard engineering terms for workflow, capability, maturity, validation method, decision, evidence, artifact boundary, and ownership. |
| [`engineering/prototype-boundaries/README.md`](engineering/prototype-boundaries/README.md) | Current implementation-owner prototype boundaries and decision gates. |
| [`testing/fixture-policy.md`](testing/fixture-policy.md) | Fixture stage, layout, expected-output, and repository-safety policy. |
| [`discovery/README.md`](discovery/README.md) | Discovery navigation for problem briefs and historical validation evidence. |
| [`discovery/problem-briefs/README.md`](discovery/problem-briefs/README.md) | Evidence-only problem briefs. |

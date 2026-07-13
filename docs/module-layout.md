# Module Layout and Dependency Direction

Status: implemented direction

Scopecat's package layout follows ownership and dependency direction rather
than the order in which the original prototype acquired files. A module name
answers two questions: which decision does this code own, and which boundaries
may it cross?

## Package responsibilities

| Package | Responsibility |
| --- | --- |
| `kernel` | Leaf identities, value types, units, immutable helpers, problems, and errors. |
| `records` | Durable and boundary-facing data records; no repositories or workflows. |
| `authoring` | Public construction DSL and immutable authoring intent. |
| `compiler.relations` | Backend-neutral relation model, proofs, uses, and evaluation ports. |
| `compiler.semantic` | Semantic graph, value expressions, availability, and operation contracts. |
| `compiler.typed` | Verified typed program IR independent of a concrete runtime. |
| `compiler.frontend` | Named passes that lower authoring intent into compiler IR. |
| `compiler.linking` | Configuration binding, realization selection, and linked-plan records. |
| `compiler.pipeline` | The application-facing compiler entry point; no historical wrapper entry points. |
| `sdk.domain` | Contracts implemented by domain adapters and runtimes. |
| `sdk.instruments` | Contracts implemented by instrument providers and drivers. |
| `planning` | Host orchestration, routing, coverage, validation, and preview projection. |
| `execution.ports` | Journal, measurement, resource, and evidence persistence interfaces. |
| `execution.local` | The local execution engine and lowering for an already prepared plan. |
| `execution` | Execution services, effects, observations, evidence, and use-case support. |
| `measurements` | Measurement contracts, projection, transforms, recording use cases, and reads. |
| `application` | Workspace-scoped port bundles shared by application use cases and composition roots. |
| `config` | Configuration validation, resolution, changes, and registry use cases. |
| `runs` | Run lifecycle, repository port, artifact access, execution, and run use cases. |
| `run_overview`, `run_comparison` | Read-side projections and comparison use cases. |
| `adapters.memory` | In-memory implementations used by contract tests and local composition. |
| `adapters.filesystem` | Filesystem implementations of repository and execution ports. |
| `composition` | The only production wiring root for concrete adapters. |
| `api` | Thin user-facing facades that validate ingress and delegate to use cases. |

## Dependency rule

Dependencies point inward toward contracts and immutable state:

```text
api
  -> application use cases (runs, config, measurements, analysis)
       -> planning / execution
            -> compiler / SDK contracts
                 -> authoring / records / kernel

composition -> application ports + concrete adapters
adapters    -> application ports + records + kernel
```

`records` does not import SDK contracts, `authoring` does not import compiler
frontend or planning workflows, and `compiler.relations` does not import the
semantic layer. `compiler.typed` does not import frontend or linking.
Application use cases do not import adapters or composition roots. Filesystem
adapters do not import workflows or facades, and production code outside
`composition` does not import filesystem implementations. These rules are
executable architecture tests rather than naming conventions alone.

Transient IR is validated when constructed or when independently produced
artifacts are bound. Provider results, effects, adapter inputs, and durable
storage remain explicit validation boundaries. Internal consumers rely on
frozen types and established invariants instead of repeating whole-object
validation.

## Composition and public surface

The local composition root constructs one `WorkspaceServices` bundle containing
the logical run repository, execution ports, and registry unit-of-work factory.
Use cases receive that bundle and never infer an adapter from a workspace path.
`RunRepository` exposes logical refs and ref kinds rather than physical paths;
registry-before-run lock ordering belongs to the workspace unit of work. The
memory composition implements the same ports for shared contract tests. The
root `scopecat` package and SDK package initializers are lazy public facades;
importing an internal leaf module does not assemble the application.

There are no forwarding modules for the retired `models`, `results`,
`domain_*`, `instruments`, `_compiler`, `_execution`, `_storage`, `_steps`, or
`_workflows` layouts. Because the project has no historical compatibility
contract, call sites move with the owning code.

## Test layout

Tests mirror the source responsibility tree. Reusable adapter behavior lives
in shared contract suites, while each memory or filesystem implementation runs
against the same suite. Architecture tests enforce dependency direction and
extension packages use public SDK/testkit boundaries rather than private
`scopecat._*` modules.

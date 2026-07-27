# Scopecat project console

Local-only React client for the Scopecat daemon. The production build is
designed to be served by the daemon so all API calls stay on relative
`/api/v1/*` paths.

```sh
pnpm install
```

For frontend development, run an API-only daemon and Vite in separate
terminals:

```sh
uv run --project ../.. scopecat serve <project> --api-only --port 8765
pnpm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8765`. Set
`SCOPECAT_DAEMON_ORIGIN` to use a different local daemon address.

`pnpm run build` writes only to this application's ignored `dist/` directory.
From the repository root, use that bundle for a source-checkout preview with
`scopecat start <project> --static-dir apps/scopecat-ui/dist`.
The repository-level `scripts/build_server_distribution.py` assembles the
server in a temporary directory and verifies that its wheel and source
distribution contain the same bundle.

`pnpm-workspace.yaml` applies the same 14-day minimum release age as Renovate
to direct and transitive dependency resolution.

## Development checks

```sh
pnpm run format:check
pnpm run lint
pnpm run typecheck
pnpm run test
```

Oxfmt owns layout and Oxlint owns correctness checks. Generated API types and
package-manager output are excluded; their producing tools remain authoritative.

## API contract

`src/api-schema.d.ts` is generated from the UI-used subset of the daemon's
OpenAPI contract. Run
`pnpm run generate:api` after changing a UI-used transport model; CI runs
`pnpm run check:api` so the generated contract cannot drift. Keep presentation
mapping in `src/api.ts`, keep stable application aliases in `src/api-contract.ts`,
and treat the generated daemon contract as authoritative.

## Browser end-to-end test

```sh
pnpm run test:e2e:install
pnpm run test:e2e
```

The test first builds the current UI into `dist/` and passes that directory
explicitly to the daemon. It then
creates a temporary starter project, starts its daemon on a dynamic port,
executes the generated first notebook, and drives the daemon-served GUI through
a parameter default and undo. It also saves a notebook analysis candidate,
accepts it in the GUI, follows its provenance back to the producing run, and
restores the previous default. The fixture removes the daemon and project after
success or an assertion failure. If identity-safe daemon shutdown itself fails,
it retains the project and reports the daemon log for manual cleanup.

## Configuration API

The configuration view uses the daemon-owned registry directly:

- `GET /api/v1/config-registry` returns `entries` and the latest `activation`.
- `GET /api/v1/config-registry/active` returns the active `entry`, `activation`,
  and immutable `config`; `404` means no entry is active.
- `GET /api/v1/config-registry/entries/{entry_id}` returns one `entry` and
  `config`.
- `POST /api/v1/config-registry/entries` registers a direct snapshot, reviewed
  draft, or approved candidate.
- `POST /api/v1/config-registry/default` atomically registers and selects the
  same revision sources.
- `POST /api/v1/config-registry/drafts/preview` validates typed parameter
  operations against the active immutable entry without writing.
- `POST /api/v1/config-registry/active` and
  `POST /api/v1/config-registry/rollback` require `expected_generation`.

The default entry exposes structured scalar and table controls. **Set as
default** is one action: the client may preview internally, then the daemon
validates, saves, and selects the result atomically. Explicit preview and
register-only controls remain available for inspection under Advanced.

When the default came from GUI parameter edits or an analysis candidate, the
summary labels it **Runtime-derived default**. The browser cannot safely decide
whether the Git/Python source has since been synchronized, so it points the
operator to `scopecat config diff .` instead of claiming drift or reloading
user code inside the daemon.

Saved-entry provenance stays descriptive rather than prescribing a calibration
workflow: manual edits link to their base entry, while analysis candidates join
the existing run, proposal, analysis, and immutable approval record.

The file picker is deliberately named **Import snapshot**: it accepts the
self-contained `scopecat.config_snapshot.v1` document registered by the daemon.

Parameter proposal lifecycle belongs to the run detail:

- `GET /api/v1/runs/{run_id}/parameter-proposals` returns proposal deltas and
  durable approval.
- `POST /api/v1/runs/{run_id}/parameter-proposals/{proposal_id}/approval`
  records one immutable approval with actor and note.
- `POST /api/v1/config-registry/default` resolves and activates the selected
  approved proposal with a generation check, then refreshes the run, event,
  proposal, and registry projections.

The ordinary GUI action is **Accept as default**. It records human acceptance
when needed and then publishes the candidate; approval-only remains Advanced.

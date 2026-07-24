# Scopecat project console

Local-only React client for the Scopecat daemon. The production build is
designed to be served by the daemon so all API calls stay on relative
`/api/v1/*` paths.

```sh
npm install
npm run dev
npm run build
```

During development, Vite proxies `/api` to `http://127.0.0.1:8765`. Set
`SCOPECAT_DAEMON_ORIGIN` to use a different local daemon address.

## Configuration API

The configuration view uses the daemon-owned registry directly:

- `GET /api/v1/config-registry` returns `entries` and `active_state`.
- `GET /api/v1/config-registry/active` returns the active `entry`, `active_state`,
  and immutable `config`; `404` means no entry is active.
- `GET /api/v1/config-registry/entries/{entry_id}` returns one `entry` and
  `config`.
- `POST /api/v1/config-registry/entries` registers an imported snapshot.
- `POST /api/v1/config-registry/drafts/preview` validates typed parameter
  operations against the active immutable entry without writing.
- `POST /api/v1/config-registry/drafts/register` registers the exact previewed
  candidate after rechecking its base generation and result hash.
- `POST /api/v1/config-registry/active` and
  `POST /api/v1/config-registry/rollback` require `expected_generation`.

The active entry exposes structured scalar and table controls. Browser edits
remain transient until preview succeeds and the operator explicitly registers
them; registration does not activate the new entry. Series and project-default
authoring remain Python workflows while their editing semantics are still
settling.

The file picker is deliberately named **Import snapshot**: it accepts the
self-contained `scopecat.config_profile_snapshot.v2` document registered by the
daemon. A split `scopecat.config_profile.v2` document must first be loaded by
Python, which resolves its references and produces the snapshot to import.

Parameter proposal lifecycle belongs to the run detail:

- `GET /api/v1/runs/{run_id}/parameter-proposals` returns proposal deltas and
  durable review decisions.
- `POST /api/v1/runs/{run_id}/parameter-proposals/{proposal_id}/review`
  appends an `approved` or `rejected` decision with reviewer and note.
- `POST /api/v1/config-registry/candidates/activate` resolves and activates the
  selected proposal when its latest decision is approved, with a generation
  check, then refreshes the run, event, proposal, and registry projections.

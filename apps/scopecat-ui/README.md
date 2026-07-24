# Scopecat workspace console

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

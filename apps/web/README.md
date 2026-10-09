# Static operator UI

`index.html` is a dependency-free static console for the synthetic DataReconcile API. Serve it with any static server, for example:

```sh
python -m http.server 4173 --directory apps/web
```

The console calls import, rows, reconcile, exceptions, resolution, finalize, and report-download APIs. It displays signed integer minor units, conservation totals, stale-version errors, and the no-transfer disclaimer. It is intentionally not an upload proxy, does not persist credentials, and must only be used with synthetic fixtures.

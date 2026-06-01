# Scenario Scripts

These scripts are executable validation scenarios, not product architecture or
public SDK examples.

## Legacy Run Storage GUI

Run:

```sh
uv run python scripts/scenarios/legacy_run_storage_gui.py
```

The script creates a synthetic legacy-system output file, records declared
legacy locators in Measurement Records storage, converts the legacy file to
normalized primary CSV, imports that CSV through the durable Measurement
Records import path, lists storage inventory, projects a measurement-oriented
review model, and writes a static HTML review page. The page leads with user
measurement entries and keeps raw storage inventory as diagnostics.

Use `--workspace ./path` to keep outputs in a specific directory. Use `--open`
to open the generated HTML page in the default browser.

The scenario deliberately does not define a final GUI, adapter framework,
legacy schema, storage schema, or import-into-existing-record behavior.

"""Export the UI-used subset of the daemon's FastAPI contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from scopecat_server.transport import DaemonApplicationContract, create_app

OUTPUT = Path(__file__).parent.parent / ".generated" / "ui-api.schema.json"

_RESPONSES = {
    "health": ("/api/v1/health", "get", "200"),
    "catalog": ("/api/v1/catalog", "get", "200"),
    "runPage": ("/api/v1/runs", "get", "200"),
    "runDetail": ("/api/v1/runs/{run_id}", "get", "200"),
    "runAnalyses": ("/api/v1/runs/{run_id}/analyses", "get", "200"),
    "artifactText": (
        "/api/v1/runs/{run_id}/artifacts/{selector}/text",
        "get",
        "200",
    ),
    "artifactJson": (
        "/api/v1/runs/{run_id}/artifacts/{selector}/json",
        "get",
        "200",
    ),
    "recordJson": (
        "/api/v1/runs/{run_id}/records/{selector}/json",
        "get",
        "200",
    ),
    "datasetContent": (
        "/api/v1/runs/{run_id}/datasets/{selector}",
        "get",
        "200",
    ),
    "measurements": ("/api/v1/runs/{run_id}/measurements", "get", "200"),
    "eventPage": ("/api/v1/events", "get", "200"),
}
_REQUESTS = {
    "attentionCommand": (
        "/api/v1/runs/{run_id}/attention",
        "post",
    ),
}


def main() -> None:
    # Route registration only closes over the backend; schema generation never calls it.
    app = create_app(cast("DaemonApplicationContract", object()))
    openapi = app.openapi()
    properties = {
        name: openapi["paths"][path][method]["responses"][status]["content"][
            "application/json"
        ]["schema"]
        for name, (path, method, status) in _RESPONSES.items()
    }
    properties.update(
        {
            name: openapi["paths"][path][method]["requestBody"]["content"][
                "application/json"
            ]["schema"]
            for name, (path, method) in _REQUESTS.items()
        }
    )
    components = openapi["components"]["schemas"]
    # These payloads are intentionally opaque in the console and recursive in JSON
    # Schema, so narrowing them here also keeps the generated contract bounded.
    for name in (
        "MeasurementRecord-Output",
        "RunRequest-Output",
        "pydantic__types__JsonValue",
        "scopecat__kernel__json_types__JsonValue",
    ):
        components[name] = {}
    reachable = _reachable_components(properties, components)
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "DaemonUiApi",
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
        "components": {
            "schemas": {name: components[name] for name in sorted(reachable)}
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _reachable_components(
    roots: object,
    components: dict[str, object],
) -> set[str]:
    pending = list(_component_refs(roots))
    found: set[str] = set()
    while pending:
        name = pending.pop()
        if name in found:
            continue
        found.add(name)
        pending.extend(_component_refs(components[name]))
    return found


def _component_refs(value: object) -> set[str]:
    if isinstance(value, dict):
        ref = value.get("$ref")
        found = (
            {ref.removeprefix("#/components/schemas/")}
            if isinstance(ref, str) and ref.startswith("#/components/schemas/")
            else set()
        )
        for item in value.values():
            found.update(_component_refs(item))
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for item in value:
            found.update(_component_refs(item))
        return found
    return set()


if __name__ == "__main__":
    main()

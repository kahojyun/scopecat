from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

PLAN_IMPLEMENTATION_ID = "scopecat.planner.local"
PLAN_IMPLEMENTATION_VERSION = "v1"


def plan_content_hash(
    *,
    experiment_id: str,
    experiment_kind: str,
    experiment_hash: str,
    parameter_build_id: str | None,
    parameter_build_hash: str | None,
    point_coordinate_ids: list[str],
    points: Sequence[BaseModel],
    parameter_patches: Sequence[BaseModel],
    desired_state: Sequence[BaseModel],
    state_patches: Sequence[BaseModel],
    acquisition: BaseModel,
    result_intents: Sequence[BaseModel],
    expected_dataset_schema: BaseModel | None,
    diagnostics: list[dict[str, Any]],
    assets: Sequence[BaseModel],
) -> str:
    return payload_hash(
        {
            "schema_version": "scopecat.plan_snapshot.v1",
            "experiment_id": experiment_id,
            "experiment_kind": experiment_kind,
            "experiment_hash": experiment_hash,
            "parameter_build_id": parameter_build_id,
            "parameter_build_hash": parameter_build_hash,
            "plan_implementation_id": PLAN_IMPLEMENTATION_ID,
            "plan_implementation_version": PLAN_IMPLEMENTATION_VERSION,
            "point_coordinate_ids": point_coordinate_ids,
            "points": [point.model_dump(mode="json") for point in points],
            "parameter_patches": [
                patch.model_dump(mode="json") for patch in parameter_patches
            ],
            "desired_state": [
                record.model_dump(mode="json") for record in desired_state
            ],
            "state_patches": [patch.model_dump(mode="json") for patch in state_patches],
            "acquisition": acquisition.model_dump(mode="json"),
            "result_intents": [
                intent.model_dump(mode="json") for intent in result_intents
            ],
            "expected_dataset_schema": (
                expected_dataset_schema.model_dump(mode="json")
                if expected_dataset_schema is not None
                else None
            ),
            "diagnostics": diagnostics,
            "assets": [ref.model_dump(mode="json") for ref in assets],
        }
    )


def payload_hash(payload: dict[str, Any]) -> str:
    content = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()

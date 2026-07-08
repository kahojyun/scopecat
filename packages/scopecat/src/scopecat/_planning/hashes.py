from __future__ import annotations

import hashlib
import json
from typing import Any


def payload_hash(payload: dict[str, Any]) -> str:
    content = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()

from __future__ import annotations

import pytest
from pydantic import ValidationError

from scopecat.config.documents import (
    CONFIG_SNAPSHOT_FORMAT_VERSION,
    config_snapshot_document_json,
    parse_config_snapshot_document,
)
from tests.testkit.workflow_fixtures import load_config


def test_config_snapshot_document_rejects_previous_format() -> None:
    content = config_snapshot_document_json(load_config()).replace(
        CONFIG_SNAPSHOT_FORMAT_VERSION,
        "scopecat.config_snapshot.v3",
        1,
    )

    with pytest.raises(ValidationError, match=r"scopecat\.config_snapshot\.v4"):
        parse_config_snapshot_document(content)

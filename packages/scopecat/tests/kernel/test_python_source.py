from __future__ import annotations

import pytest

from scopecat.kernel.python_source import python_source_identity


def _source_definition(value: int) -> int:
    return value + 1


def test_python_source_identity_retains_exact_import_and_lexical_source() -> None:
    assert python_source_identity(
        _source_definition,
        label="test definition",
    ) == {
        "module": __name__,
        "qualname": "_source_definition",
        "source": "def _source_definition(value: int) -> int:\n    return value + 1",
    }


def test_python_source_identity_reports_unavailable_source_with_domain_label() -> None:
    with pytest.raises(
        TypeError,
        match="test builtin source must be available to fingerprint",
    ):
        python_source_identity(len, label="test builtin")

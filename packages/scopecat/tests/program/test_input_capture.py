from __future__ import annotations

from scopecat.program.input_capture import capture_runtime_input


def test_runtime_input_capture_freezes_nested_values() -> None:
    items = [1]
    nested: dict[str, object] = {"items": items}
    source: dict[str, object] = {"nested": nested}

    captured = capture_runtime_input(source)
    items.append(2)
    nested["mode"] = "changed"
    source["other"] = "changed"

    assert captured == {"nested": {"items": (1,)}}

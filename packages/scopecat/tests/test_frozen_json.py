from scopecat.kernel.frozen import freeze_json_mapping, thaw_json_value


def test_thaw_recurses_through_mixed_lists_tuples_and_frozen_mappings() -> None:
    frozen = freeze_json_mapping({"details": [{"attempt": 1}]})
    source = {"segments": [{"metadata": frozen}], "tuple": (frozen,)}
    result = thaw_json_value(source)
    assert result == {
        "segments": [{"metadata": {"details": [{"attempt": 1}]}}],
        "tuple": [{"details": [{"attempt": 1}]}],
    }
    assert source["segments"][0]["metadata"] is frozen

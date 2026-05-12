"""Text-only fixture code for the minimal unknown fixture."""

raise RuntimeError("fixture code must not be executed")

SETTING_PATH = "setting/parameters.json"


def describe_reopen_flow():
    return {
        "read": SETTING_PATH,
        "snapshot": null,
        "sidecars": [],
    }

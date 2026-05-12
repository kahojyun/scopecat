"""Text-only fixture code.

This intentionally raises at import time so tests can catch accidental
execution. Static analysis should only inspect the text.
"""

raise RuntimeError("fixture code must not be executed")


def describe_flow(setting_path, data_path):
    return {
        "read": f"{setting_path}/parameters.json",
        "snapshot": f"{data_path}/run-00042-parameters.json",
        "sidecars": [
            f"{setting_path}/temp/chip_info.json",
            f"{setting_path}/temp/line_info.json",
        ],
    }

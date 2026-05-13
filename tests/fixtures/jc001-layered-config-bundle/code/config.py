"""Text-only fixture code.

The passive evidence-view prototype must read this file as text. It must not
import or execute it.
"""

raise RuntimeError("fixture code must not be executed")

SETTING_PATH = "setting"
DATA_PATH = "data"
OPTIONAL_SIDECARS = {
    "generated_chip": "setting/temp/chip_info.json",
    "generated_line": "setting/temp/line_info.json",
}

"""Public-safe inert code fixture.

This file is evidence text only. Static-analysis prototypes must not execute it.
"""

raise RuntimeError("fixture code must not be executed")


def run_public_template(context):
    return {"version": "main-v2", "context": context}

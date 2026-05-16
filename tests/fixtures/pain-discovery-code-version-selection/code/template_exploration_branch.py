"""Public-safe inert code fixture.

This file is evidence text only. Static-analysis prototypes must not execute it.
"""


def run_public_template(context):
    return {"version": "exploration-branch", "context": context}

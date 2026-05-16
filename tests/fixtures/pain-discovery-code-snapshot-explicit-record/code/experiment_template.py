"""Text-only public fixture.

The pain-discovery fixture treats this file as inert evidence. It must not be
imported or executed by Scopecat validation code.
"""

raise RuntimeError("fixture code must not be executed")


def run_public_template(context, recorder):
    recorder.add_parameter("public_axis", [0, 1, 2])
    recorder.add_context_ref("setting-snapshot-alpha")
    return "public-placeholder"

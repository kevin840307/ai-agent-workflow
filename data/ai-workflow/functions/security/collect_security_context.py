from __future__ import annotations

FUNCTION_META = {
    "id": "collect_security_context",
    "label": "Collect Security Context",
    "description": "Write bounded security scan scope and excerpts to output/security-context.md.",
    "ui": {"tabs": ['basic', 'retry', 'advanced']},
}

from app.workflow_runtime.builtin_functions.security_context import collect_security_context as _impl


def run(context, artifact=None):
    if artifact is not None:
        return _impl(context, artifact)
    return _impl(context)

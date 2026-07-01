from __future__ import annotations

FUNCTION_META = {
    "id": "require_status_pass",
    "label": "Require Status PASS",
    "description": "Gate helper for artifacts that must contain Status: PASS.",
    "ui": {"tabs": ['basic', 'gate', 'retry', 'advanced']},
}

from app.workflow_runtime.builtin_functions.core import require_status_pass as _impl


def run(context, artifact=None):
    if artifact is not None:
        return _impl(context, artifact)
    return _impl(context)

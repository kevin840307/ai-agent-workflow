from __future__ import annotations

FUNCTION_META = {
    "id": "validate_todo",
    "label": "Validate Todo",
    "description": "Check todo sections, TEST IDs, and AC coverage.",
    "ui": {"tabs": ['basic', 'retry', 'advanced']},
}

from app.workflow_runtime.builtin_functions.core import validate_todo as _impl


def run(context, artifact=None):
    if artifact is not None:
        return _impl(context, artifact)
    return _impl(context)

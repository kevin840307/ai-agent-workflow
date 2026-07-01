from __future__ import annotations

FUNCTION_META = {
    "id": "validate_spec",
    "label": "Validate Spec",
    "description": "Check required spec sections and AC IDs.",
    "ui": {"tabs": ['basic', 'retry', 'advanced']},
}

from app.workflow_runtime.builtin_functions.core import validate_spec as _impl


def run(context, artifact=None):
    if artifact is not None:
        return _impl(context, artifact)
    return _impl(context)

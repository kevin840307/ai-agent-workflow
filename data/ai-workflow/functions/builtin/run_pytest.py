from __future__ import annotations

FUNCTION_META = {
    "id": "run_pytest",
    "label": "Run Pytest",
    "description": "Run the configured Python test command and write output/test-result.md.",
    "ui": {"tabs": ['basic', 'retry', 'advanced']},
}

from app.workflow_runtime.builtin_functions.core import run_pytest as _impl


def run(context, artifact=None):
    if artifact is not None:
        return _impl(context, artifact)
    return _impl(context)

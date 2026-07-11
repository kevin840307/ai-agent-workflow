from __future__ import annotations

FUNCTION_META = {
    "id": "adaptive_python_gate",
    "label": "Adaptive Python Gate",
    "description": "Run configured validation, pytest, or run_tests.py; report NOT_CONFIGURED when no optional validator exists and never fabricate PASS evidence.",
    "ui": {"tabs": ["basic", "retry", "advanced"]},
}

from app.workflow_runtime.builtin_functions.core import adaptive_python_gate as _impl


def run(context, artifact=None):
    if artifact is not None:
        return _impl(context, artifact)
    return _impl(context)

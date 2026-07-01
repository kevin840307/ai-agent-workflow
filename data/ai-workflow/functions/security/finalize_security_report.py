from __future__ import annotations

FUNCTION_META = {
    "id": "finalize_security_report",
    "label": "Finalize Security Report",
    "description": "Write output/security-final.md after report validation passes.",
    "ui": {"tabs": ['basic', 'retry', 'advanced']},
}

from app.workflow_runtime.builtin_functions.security_validation import finalize_security_report as _impl


def run(context, artifact=None):
    if artifact is not None:
        return _impl(context, artifact)
    return _impl(context)

from __future__ import annotations

FUNCTION_META = {
    "id": "generate_security_report",
    "label": "Generate Security Report",
    "description": "Generate output/security-report.md from normalized security findings.",
    "ui": {"tabs": ['basic', 'retry', 'advanced']},
}

from app.workflow_runtime.builtin_functions.security_validation import generate_security_report as _impl


def run(context, artifact=None):
    if artifact is not None:
        return _impl(context, artifact)
    return _impl(context)

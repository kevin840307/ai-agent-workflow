from __future__ import annotations

FUNCTION_META = {
    "id": "validate_security_report",
    "label": "Validate Security Report",
    "description": "Score output/security-report.md and fail below thresholds.",
    "ui": {"tabs": ['basic', 'retry', 'advanced']},
}

from app.workflow_runtime.builtin_functions.security_validation import validate_security_report as _impl


def run(context, artifact=None):
    if artifact is not None:
        return _impl(context, artifact)
    return _impl(context)

from __future__ import annotations

FUNCTION_META = {
    "id": "validate_security_candidates",
    "label": "Validate Security Candidates",
    "description": "Score one AI-generated security candidate artifact and fail below thresholds.",
    "ui": {"tabs": ['basic', 'retry', 'advanced']},
}

from app.workflow_runtime.builtin_functions.security_validation import validate_security_candidates as _impl


def run(context, artifact=None):
    if artifact is not None:
        return _impl(context, artifact)
    return _impl(context)

from __future__ import annotations

FUNCTION_META = {
    "id": "combine_security_candidates",
    "label": "Combine Security Candidates",
    "description": "Merge same-task multi-agent security candidate files and compute consensus confidence.",
    "ui": {"tabs": ['basic', 'retry', 'advanced']},
}

from app.workflow_runtime.builtin_functions.security_validation import combine_security_candidates as _impl


def run(context, artifact=None):
    if artifact is not None:
        return _impl(context, artifact)
    return _impl(context)

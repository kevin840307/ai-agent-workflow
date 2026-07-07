"""Execution-facing workflow runtime package.

This package is the stable import surface for workflow execution concerns.  It
keeps the public architecture clear even while legacy modules remain available
for backwards compatibility.
"""
from app.workflow_runtime.executor import WorkflowExecutor

__all__ = ["WorkflowExecutor"]

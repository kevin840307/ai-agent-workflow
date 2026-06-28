from __future__ import annotations


class WorkflowError(Exception):
    pass


class ValidationError(WorkflowError):
    pass


class UserInputRequired(WorkflowError):
    pass


class WorkflowCancelled(WorkflowError):
    pass

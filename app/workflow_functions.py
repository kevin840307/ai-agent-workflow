"""Compatibility facade for workflow function imports.

The implementation is intentionally split under ``app.workflow_function_modules``.
Keep this module small so old imports such as ``from app.workflow_functions import ...``
continue to work while each workflow function group remains maintainable.
"""
from __future__ import annotations

from app.workflow_function_catalog import AVAILABLE_WORKFLOW_FUNCTIONS
from app.workflow_function_modules import base as _base
from app.workflow_function_modules import core as _core
from app.workflow_function_modules import registry as _registry
from app.workflow_function_modules import security_context as _security_context
from app.workflow_function_modules import security_validation as _security_validation


def _export_module(module) -> None:
    for name, value in vars(module).items():
        if name.startswith("__"):
            continue
        if name in {"annotations"}:
            continue
        globals()[name] = value


for _module in (_base, _core, _security_context, _security_validation, _registry):
    _export_module(_module)

__all__ = sorted(
    name
    for name in globals()
    if not name.startswith("_module")
    and name not in {"_base", "_core", "_registry", "_security_context", "_security_validation", "_export_module"}
)

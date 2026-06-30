"""Compatibility imports for the old controllers package."""

from app.api.routes import artifacts as artifact_controller
from app.api.routes import config as config_controller
from app.api.routes import maintenance as maintenance_controller
from app.api.routes import projects as project_controller
from app.api.routes import workflows as workflow_config_controller
from app.api.routes import workflow_runs as workflow_controller

__all__ = [
    "artifact_controller",
    "config_controller",
    "maintenance_controller",
    "project_controller",
    "workflow_config_controller",
    "workflow_controller",
]

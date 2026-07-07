from __future__ import annotations

from typing import Any, Awaitable, Callable

from .action_helpers import (
    config_for_step,
    fresh_session_for_step,
    is_adaptive_workflow,
    is_auto_development_workflow,
    is_general_auto_development_workflow,
)
from .agent_step_runner import AgentStepRunner
from .functions import WorkflowFunctionService
from .base_actions import BaseAgentActionsMixin
from .general_actions import GeneralDevelopmentActionsMixin
from .adaptive_actions import AdaptiveWorkflowActionsMixin
from .consensus_actions import ConsensusActionsMixin
from .review_actions import ReviewActionsMixin
from .task_loop_actions import TaskLoopActionsMixin
from .action_dispatcher import ActionDispatcherMixin
from .actions_registry import builtin_action_for_step  # compatibility: dispatcher-owned builtin action table

LogFn = Callable[[dict[str, Any], str], Awaitable[None]]
RefreshArtifactsFn = Callable[[str], Awaitable[Any]]


class WorkflowActions(
    ActionDispatcherMixin,
    ConsensusActionsMixin,
    AdaptiveWorkflowActionsMixin,
    GeneralDevelopmentActionsMixin,
    ReviewActionsMixin,
    TaskLoopActionsMixin,
    BaseAgentActionsMixin,
):
    """Step action registry driven by workflow assets.

    This class is intentionally thin.  Concrete step families live in focused
    mixins so validation, adaptive, review, consensus, and agent execution can
    evolve independently without growing a single monolithic runtime file.
    """

    def __init__(
        self,
        *,
        agent_runner: AgentStepRunner,
        functions: WorkflowFunctionService,
        log: LogFn,
        refresh_artifacts: RefreshArtifactsFn,
    ) -> None:
        self.agent_runner = agent_runner
        self.functions = functions
        self.log = log
        self.refresh_artifacts = refresh_artifacts

    _is_auto_development_workflow = staticmethod(is_auto_development_workflow)
    _is_general_auto_development_workflow = staticmethod(is_general_auto_development_workflow)
    _is_adaptive_workflow = staticmethod(is_adaptive_workflow)
    _fresh_session_for_step = staticmethod(fresh_session_for_step)
    _config_for_step = staticmethod(config_for_step)

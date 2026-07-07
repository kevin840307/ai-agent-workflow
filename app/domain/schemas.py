from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CreateMessageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    content: str = Field(min_length=1)
    client_request_id: str | None = Field(default=None, alias="clientRequestId")
    thinking_level: str | None = Field(default=None, alias="thinkingLevel")


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    requirement: str | None = None
    test_command: str | None = None
    validation_script: str | None = None
    project_path: str | None = None
    workflow_id: str | None = None
    skill: str | None = None
    config: str | None = None
    agent: str | None = None
    run_profile: str | None = Field(default=None, alias="runProfile")
    thinking_level: str | None = Field(default=None, alias="thinkingLevel")
    run_timeout_sec: int | None = Field(default=None, alias="runTimeoutSec")
    patch_mode: str | None = Field(default=None, alias="patchMode")
    workflow_version: str | None = Field(default=None, alias="workflowVersion")
    prompt_version: str | None = Field(default=None, alias="promptVersion")
    contract_version: str | None = Field(default=None, alias="contractVersion")
    context_pack: str | None = Field(default=None, alias="contextPack")


class CreateSessionRequest(BaseModel):
    project_path: str | None = None
    title: str | None = None


class AgentSettingsRequest(BaseModel):
    auth_type: str | None = None
    reuse_session: bool | None = None
    max_retries: int | None = None
    default_agent: str | None = None
    opencode_bin: str | None = None
    opencode_mode: str | None = None
    opencode_reuse_session: bool | None = None
    opencode_timeout_sec: int | None = None
    opencode_model: str | None = None
    opencode_agent: str | None = None


class RetryRunRequest(BaseModel):
    step_key: str | None = None


class SubmitAnswersRequest(BaseModel):
    content: str = Field(min_length=1)
    step_key: str | None = None


class SubmitGuidanceRequest(BaseModel):
    content: str = Field(min_length=1)
    step_key: str


class StepControlRequest(BaseModel):
    step_key: str
    reason: str | None = None

class PatchApplyRequest(BaseModel):
    files: list[str] | None = None


class RerunStepRequest(BaseModel):
    step_key: str | None = None
    mode: str | None = Field(default="from_step", description="from_step, current_step, or validation_only")
    reason: str | None = None


__all__ = [
    "CreateMessageRequest",
    "CreateRunRequest",
    "CreateSessionRequest",
    "AgentSettingsRequest",
    "RetryRunRequest",
    "SubmitAnswersRequest",
    "SubmitGuidanceRequest",
    "StepControlRequest",
    "PatchApplyRequest",
    "RerunStepRequest",
]

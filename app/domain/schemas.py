from __future__ import annotations

from pydantic import BaseModel, Field


class CreateMessageRequest(BaseModel):
    content: str = Field(min_length=1)


class CreateRunRequest(BaseModel):
    requirement: str | None = None
    test_command: str | None = None
    project_path: str | None = None
    workflow_id: str | None = None


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

__all__ = [
    "CreateMessageRequest",
    "CreateRunRequest",
    "CreateSessionRequest",
    "AgentSettingsRequest",
    "RetryRunRequest",
    "SubmitAnswersRequest",
    "SubmitGuidanceRequest",
]

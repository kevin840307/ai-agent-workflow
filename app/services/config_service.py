from __future__ import annotations

from fastapi import HTTPException

from app import runtime


def get_config() -> dict:
    return {"qwen": runtime.qwen_runtime_config()}


def update_qwen_config(body: runtime.QwenSettingsRequest) -> dict:
    allowed = {"", "openai", "anthropic", "qwen-oauth", "gemini", "vertex-ai"}
    auth_type = (body.auth_type or "").strip()
    if auth_type not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported auth type: {auth_type}")
    settings = runtime.load_settings()
    settings["qwen"]["auth_type"] = auth_type
    if body.reuse_session is not None:
        settings["qwen"]["reuse_session"] = body.reuse_session
    if body.max_retries is not None:
        settings["qwen"]["max_retries"] = max(0, min(10, int(body.max_retries)))
    runtime.save_settings(settings)
    return {"qwen": runtime.qwen_runtime_config()}

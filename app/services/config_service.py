from __future__ import annotations

from fastapi import HTTPException

from app.runtime_modules import api as runtime


def get_config() -> dict:
    return {"qwen": runtime.qwen_runtime_config()}


def update_agent_config(body: runtime.AgentSettingsRequest) -> dict:
    allowed = {"", "openai", "anthropic", "qwen-oauth", "gemini", "vertex-ai"}
    auth_type = (body.auth_type or "").strip()
    if auth_type not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported auth type: {auth_type}")
    settings = runtime.load_settings()
    settings["qwen"]["auth_type"] = auth_type
    if body.max_retries is not None:
        settings["qwen"]["max_retries"] = max(0, min(10, int(body.max_retries)))
    settings.setdefault("agents", {})
    settings["agents"].setdefault("providers", {})
    settings["agents"]["providers"].setdefault("qwen", {"type": "qwen_cli"})
    settings["agents"]["providers"].setdefault(
        "opencode",
        {"type": "opencode_cli", "bin": "opencode", "mode": "run", "reuseSession": True, "timeoutSec": 1200},
    )
    if body.reuse_session is not None:
        settings["qwen"]["reuse_session"] = body.reuse_session
        settings["agents"]["providers"]["opencode"]["reuseSession"] = body.reuse_session
    if body.default_agent is not None:
        default_agent = body.default_agent.strip() or "qwen"
        if default_agent not in settings["agents"]["providers"]:
            raise HTTPException(status_code=400, detail=f"Unsupported default agent: {default_agent}")
        settings["agents"]["default"] = default_agent
    if body.opencode_bin is not None:
        settings["agents"]["providers"]["opencode"]["bin"] = body.opencode_bin.strip() or "opencode"
    if body.opencode_mode is not None:
        opencode_mode = body.opencode_mode.strip() or "run"
        if opencode_mode not in {"run", "prompt_flag"}:
            raise HTTPException(status_code=400, detail=f"Unsupported opencode mode: {opencode_mode}")
        settings["agents"]["providers"]["opencode"]["mode"] = opencode_mode
    if body.opencode_reuse_session is not None and body.reuse_session is None:
        settings["agents"]["providers"]["opencode"]["reuseSession"] = body.opencode_reuse_session
    if body.opencode_timeout_sec is not None:
        settings["agents"]["providers"]["opencode"]["timeoutSec"] = max(1, min(86400, int(body.opencode_timeout_sec)))
    if body.opencode_model is not None:
        value = body.opencode_model.strip()
        if value:
            settings["agents"]["providers"]["opencode"]["model"] = value
        else:
            settings["agents"]["providers"]["opencode"].pop("model", None)
    if body.opencode_agent is not None:
        value = body.opencode_agent.strip()
        if value:
            settings["agents"]["providers"]["opencode"]["agent"] = value
        else:
            settings["agents"]["providers"]["opencode"].pop("agent", None)
    runtime.save_settings(settings)
    return {"qwen": runtime.qwen_runtime_config()}

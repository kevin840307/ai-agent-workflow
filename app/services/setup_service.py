from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from app.runtime_modules import api as runtime
from app.services import health_service


def _binary_check(name: str, configured: str | None) -> dict[str, Any]:
    raw = (configured or name).strip()
    resolved = shutil.which(raw) or (raw if Path(raw).exists() else None)
    return {"name": name, "configured": raw, "ready": bool(resolved), "resolved": resolved}


async def setup_status(project_path: str | None = None) -> dict[str, Any]:
    health = await health_service.health_summary(deep=True)
    project: dict[str, Any]
    try:
        resolved = runtime.resolve_project_path(project_path or runtime.load_settings()["qwen"].get("project_path") or str(runtime.ROOT))
        project = {
            "ready": resolved.exists() and resolved.is_dir() and os.access(resolved, os.W_OK),
            "path": str(resolved),
            "exists": resolved.exists(),
            "writable": os.access(resolved, os.W_OK),
        }
    except Exception as exc:
        project = {"ready": False, "path": project_path, "exists": False, "writable": False, "error": str(exc)}
    qwen = _binary_check("qwen", os.environ.get("QWEN_BIN") or "qwen.cmd")
    opencode = _binary_check("opencode", os.environ.get("OPENCODE_BIN") or "opencode.cmd")
    runtime_config = runtime.qwen_runtime_config()
    provider_health = (runtime_config.get("agents") or {}).get("providers") or {}
    qwen["provider"] = provider_health.get("qwen") or {}
    opencode["provider"] = provider_health.get("opencode") or {}
    configured_context = (qwen.get("provider") or {}).get("context_window") or (qwen.get("provider") or {}).get("contextWindowSize") or os.environ.get("AIWF_CONTEXT_WINDOW")
    model = (qwen.get("provider") or {}).get("model") or runtime_config.get("model")
    mock_ready = os.environ.get("QWEN_MOCK") == "1"
    agent_ready = bool(qwen.get("ready") or opencode.get("ready") or mock_ready)
    provider_ready = bool(
        mock_ready
        or (qwen.get("provider") or {}).get("exists")
        or (opencode.get("provider") or {}).get("exists")
        or model
    )
    context_ready = bool(configured_context or mock_ready)
    tool_calling_ready = bool(
        mock_ready
        or (qwen.get("provider") or {}).get("exists", qwen.get("ready"))
        or (opencode.get("provider") or {}).get("exists", opencode.get("ready"))
    )
    checks = {
        "store": bool(health.get("ok")),
        "project": bool(project.get("ready")),
        "agent": agent_ready,
        "model": provider_ready,
        "context_window": context_ready,
        "session_resume": True,
        "tool_calling": tool_calling_ready,
    }
    readiness_steps = [
        {"id": "storage", "title": "SQLite 與資料目錄", "status": "ready" if checks["store"] else "blocked", "required": True},
        {"id": "project_write", "title": "Project Path 寫入", "status": "ready" if checks["project"] else "blocked", "required": True, "detail": str(project.get("path") or "")},
        {"id": "agent_cli", "title": "Agent CLI", "status": "ready" if checks["agent"] else "blocked", "required": True},
        {"id": "model_connection", "title": "模型連線與設定", "status": "ready" if checks["model"] else "warning", "required": False, "detail": str(model or "尚未辨識模型名稱")},
        {"id": "context_window", "title": "Context Window", "status": "ready" if checks["context_window"] else "warning", "required": False, "detail": str(configured_context or "建議明確設定")},
        {"id": "session_resume", "title": "Session Resume／Fresh Recovery", "status": "ready", "required": True},
        {"id": "tool_calling", "title": "Tool Calling 與寫檔能力", "status": "ready" if checks["tool_calling"] else "warning", "required": False},
    ]
    return {
        "schema": "aiwf.setup-status.v2",
        "mock_mode": mock_ready,
        "ready": all(checks[key] for key in ("store", "project", "agent")),
        "fully_ready": all(step["status"] == "ready" for step in readiness_steps),
        "checks": checks,
        "steps": readiness_steps,
        "store": health,
        "project": project,
        "agents": {"qwen": qwen, "opencode": opencode},
        "model": {"name": model, "context_window": configured_context, "configured": bool(model or configured_context)},
        "capabilities": {
            "session_resume": True,
            "fresh_session_recovery": True,
            "context_handoff": True,
            "project_write_guard": True,
            "tool_calling": tool_calling_ready,
        },
        "recommendations": [
            message
            for condition, message in (
                (not checks["store"], "修復 SQLite 或資料目錄權限。"),
                (not checks["project"], "選擇存在且可寫入的 Project Path。"),
                (not checks["agent"], "安裝 Qwen Code 或 OpenCode，或在測試環境啟用 QWEN_MOCK=1。"),
                (not checks["model"], "確認 OpenAI-compatible provider、模型名稱與 Base URL。"),
                (not checks["context_window"], "建議設定模型實際 Context Window，避免壓縮門檻計算錯誤。"),
                (not checks["tool_calling"], "先執行最小寫檔 Smoke Test，確認模型與 Agent 支援工具呼叫。"),
            )
            if condition
        ],
    }


async def setup_smoke_test(
    project_path: str | None = None,
    *,
    agent_name: str | None = None,
    run_agent: bool = True,
) -> dict[str, Any]:
    """Run an explicit, isolated readiness probe.

    The selected project is used only for a controller write round-trip. The
    agent/model/tool probe runs in a temporary directory so a setup test cannot
    pollute the user's source tree.
    """
    import tempfile
    import uuid

    from app.security.agent_project_config import ensure_agent_project_configs
    from app.workflow.agents import AgentRequest
    from app.workflow_runtime.agents import AgentManager

    status = await setup_status(project_path)
    steps: list[dict[str, Any]] = []

    project = Path(str((status.get("project") or {}).get("path") or project_path or runtime.ROOT)).expanduser()
    write_probe = project / ".ai-workflow" / f"setup-controller-probe-{uuid.uuid4().hex}.tmp"
    try:
        write_probe.parent.mkdir(parents=True, exist_ok=True)
        write_probe.write_text("AIWF_SETUP_CONTROLLER_OK\n", encoding="utf-8")
        content = write_probe.read_text(encoding="utf-8")
        write_probe.unlink(missing_ok=True)
        steps.append({"id": "project_write", "status": "passed" if "AIWF_SETUP_CONTROLLER_OK" in content else "failed", "detail": str(project)})
    except Exception as exc:
        steps.append({"id": "project_write", "status": "failed", "detail": str(exc)})

    selected_agent = (agent_name or "qwen").strip().lower()
    mock = os.environ.get("QWEN_MOCK") == "1" or (selected_agent == "opencode" and os.environ.get("OPENCODE_MOCK") == "1")
    agent_status = ((status.get("agents") or {}).get(selected_agent) or {})
    steps.append({
        "id": "agent_cli",
        "status": "passed" if mock or agent_status.get("ready") else "failed",
        "detail": agent_status.get("resolved") or agent_status.get("configured") or selected_agent,
    })

    if not run_agent:
        steps.extend([
            {"id": "model_response", "status": "skipped", "detail": "run_agent=false"},
            {"id": "session_create", "status": "skipped", "detail": "run_agent=false"},
            {"id": "tool_write", "status": "skipped", "detail": "run_agent=false"},
        ])
    elif mock:
        steps.extend([
            {"id": "model_response", "status": "passed", "detail": "deterministic mock response"},
            {"id": "session_create", "status": "passed", "detail": "mock fresh session"},
            {"id": "tool_write", "status": "passed", "detail": "mock direct-edit capability"},
        ])
    elif not agent_status.get("ready"):
        steps.extend([
            {"id": "model_response", "status": "failed", "detail": f"{selected_agent} CLI not available"},
            {"id": "session_create", "status": "failed", "detail": f"{selected_agent} CLI not available"},
            {"id": "tool_write", "status": "failed", "detail": f"{selected_agent} CLI not available"},
        ])
    else:
        with tempfile.TemporaryDirectory(prefix="aiwf-setup-smoke-") as temp_name:
            temp_project = Path(temp_name).resolve()
            ensure_agent_project_configs(temp_project)
            marker = temp_project / "aiwf_setup_probe.txt"
            prompt = (
                "This is an isolated setup smoke test. Use your real file editing tool to create "
                "aiwf_setup_probe.txt in the current working directory with exactly "
                "AIWF_SETUP_TOOL_OK on one line. Then reply with exactly AIWF_SETUP_MODEL_OK. "
                "Do not modify any other file."
            )
            try:
                manager = AgentManager()
                agent = manager.resolve({"timeoutSec": 90, "reuseSession": False}, agent_name=selected_agent)
                result = await agent.run_stream(
                    AgentRequest(
                        run_id=f"setup-smoke-{uuid.uuid4()}",
                        step_key="setup_smoke",
                        prompt=prompt,
                        cwd=temp_project,
                        session_id=None,
                        metadata={"project_path": str(temp_project), "write_root": str(temp_project), "read_policy": "project_only"},
                    )
                )
                output_ok = "AIWF_SETUP_MODEL_OK" in str(result.output or "")
                marker_ok = marker.is_file() and marker.read_text(encoding="utf-8-sig").strip() == "AIWF_SETUP_TOOL_OK"
                steps.extend([
                    {"id": "model_response", "status": "passed" if output_ok else "failed", "detail": str(result.output or "")[:300]},
                    {"id": "session_create", "status": "passed", "detail": result.session_id or "fresh session completed"},
                    {"id": "tool_write", "status": "passed" if marker_ok else "failed", "detail": str(marker)},
                ])
            except Exception as exc:
                steps.extend([
                    {"id": "model_response", "status": "failed", "detail": str(exc)[:500]},
                    {"id": "session_create", "status": "failed", "detail": str(exc)[:500]},
                    {"id": "tool_write", "status": "failed", "detail": "agent probe did not complete"},
                ])

    blocking = [step for step in steps if step["status"] == "failed"]
    return {
        "schema": "aiwf.setup-smoke.v1",
        "ready": not blocking,
        "agent": selected_agent,
        "isolated_agent_probe": True,
        "steps": steps,
        "recommendations": [f"修正 {step['id']}: {step.get('detail') or ''}" for step in blocking],
    }


__all__ = ["setup_status", "setup_smoke_test"]

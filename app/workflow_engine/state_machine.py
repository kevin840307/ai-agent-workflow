from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.paths import utc_now


RUN_TRANSITIONS: dict[str, set[str]] = {
    "": {"queued", "running", "failed", "cancelled"},
    "queued": {"queued", "running", "waiting_input", "cancelling", "done", "cancelled", "failed"},
    "running": {"running", "waiting_input", "queued", "cancelling", "done", "failed", "cancelled"},
    "waiting_input": {"waiting_input", "queued", "running", "cancelling", "done", "failed", "cancelled"},
    "cancelling": {"cancelling", "cancelled", "failed"},
    "failed": {"failed", "queued", "running", "cancelled"},
    "cancelled": {"cancelled", "queued", "running"},
    "done": {"done", "queued", "running"},
}

STEP_TRANSITIONS: dict[str, set[str]] = {
    "": {"pending", "running", "passed", "failed", "skipped", "waiting_input", "cancelled"},
    "pending": {"pending", "running", "passed", "failed", "skipped", "waiting_input", "cancelled"},
    "running": {"running", "passed", "failed", "skipped", "waiting_input", "cancelled", "pending"},
    "waiting_input": {"waiting_input", "running", "pending", "failed", "cancelled", "skipped"},
    "failed": {"failed", "pending", "running", "passed", "skipped", "cancelled"},
    "passed": {"passed", "pending", "running"},
    "skipped": {"skipped", "pending", "running", "passed"},
    "cancelled": {"cancelled", "pending", "running"},
}

USER_STEP_TITLES = {
    "plan_tasks": "分析需求",
    "generate_task_prompts": "分析需求",
    "build": "實作功能",
    "auto_generation": "實作功能",
    "generate_tests": "建立測試",
    "run_test": "執行測試",
    "adaptive_python_gate": "執行驗證",
    "external_validation": "外部驗證",
    "implementation_review": "檢查品質",
    "ai_review": "檢查品質",
    "final_review": "最終確認",
    "final_gate": "完成驗收",
}


class InvalidTransition(ValueError):
    pass


@dataclass(slots=True)
class TransitionDecision:
    allowed: bool
    source: str
    target: str
    reason: str


def validate_transition(kind: str, source: str | None, target: str, *, strict: bool = True) -> TransitionDecision:
    source = str(source or "")
    target = str(target or "")
    table = RUN_TRANSITIONS if kind == "run" else STEP_TRANSITIONS
    allowed = target in table.get(source, set())
    reason = "allowed" if allowed else f"invalid {kind} transition: {source or '<new>'} -> {target}"
    if strict and not allowed:
        raise InvalidTransition(reason)
    return TransitionDecision(allowed=allowed, source=source, target=target, reason=reason)


def append_transition(record: dict[str, Any], *, kind: str, source: str | None, target: str, reason: str | None = None) -> None:
    record.setdefault("transitions", []).append(
        {
            "kind": kind,
            "from": source,
            "to": target,
            "reason": reason or "status update",
            "at": utc_now(),
        }
    )
    # Bound embedded state. Full event history is persisted separately by the
    # event store / normalized SQLite projection.
    if len(record["transitions"]) > 100:
        record["transitions"] = record["transitions"][-100:]


def friendly_step_title(step: dict[str, Any] | str | None) -> str:
    if isinstance(step, dict):
        key = str(step.get("key") or "")
        explicit = step.get("display_name") or step.get("displayName") or step.get("title") or step.get("name")
        if explicit and str(explicit).strip() and str(explicit).strip() != key:
            return str(explicit).strip()
    else:
        key = str(step or "")
    if key in USER_STEP_TITLES:
        return USER_STEP_TITLES[key]
    normalized = key.replace("_", " ").replace("-", " ").strip()
    return normalized.title() if normalized else "準備中"


def phase_for_step(step: dict[str, Any] | None, run_status: str | None = None) -> str:
    status = str(run_status or "")
    if status == "done":
        return "completed"
    if status in {"failed", "cancelled"}:
        return status
    if status == "waiting_input":
        return "waiting_input"
    key = str((step or {}).get("key") or "").lower()
    if any(token in key for token in ("plan", "prompt")):
        return "planning"
    if any(token in key for token in ("test", "validation", "gate")):
        return "validating"
    if "review" in key:
        return "reviewing"
    if status in {"queued", ""}:
        return "queued"
    return "executing"


def current_step(run: dict[str, Any]) -> dict[str, Any] | None:
    steps = list(run.get("steps") or [])
    return next((step for step in steps if step.get("status") in {"running", "waiting_input"}), None) or next(
        (step for step in steps if step.get("status") == "pending"), None
    )


def derive_current_action(run: dict[str, Any]) -> dict[str, Any]:
    step = current_step(run)
    phase = phase_for_step(step, run.get("status"))
    title = friendly_step_title(step)
    status = str(run.get("status") or "queued")
    if status == "done":
        return {"phase": phase, "title": "執行完成", "detail": "所有必要步驟與驗證已完成。", "next": "查看變更與驗證結果。"}
    if status == "failed":
        return {
            "phase": phase,
            "title": "需要處理",
            "detail": str(run.get("error") or (step or {}).get("error") or "Workflow 執行失敗。"),
            "next": "查看建議動作或開啟技術診斷。",
        }
    if status == "waiting_input":
        return {"phase": phase, "title": "等待你的回覆", "detail": str((step or {}).get("error") or "需要更多資訊才能繼續。"), "next": "提交答案後會自動繼續。"}
    timeline = list(run.get("timeline") or run.get("events") or [])
    step_key = (step or {}).get("key")
    latest_event = next(
        (event for event in reversed(timeline) if not step_key or (event.get("step_key") or event.get("stepKey")) in {None, step_key}),
        None,
    )
    detail = str((step or {}).get("last_event") or (latest_event or {}).get("message") or "系統正在處理目前步驟。")
    next_pending = None
    if step:
        steps = list(run.get("steps") or [])
        try:
            index = steps.index(step)
            next_pending = next((item for item in steps[index + 1 :] if item.get("status") == "pending"), None)
        except ValueError:
            next_pending = None
    return {
        "phase": phase,
        "title": title,
        "detail": detail,
        "next": f"接下來：{friendly_step_title(next_pending)}" if next_pending else "完成後會整理變更與驗證結果。",
        "step_key": (step or {}).get("key"),
    }


__all__ = [
    "InvalidTransition",
    "TransitionDecision",
    "validate_transition",
    "append_transition",
    "friendly_step_title",
    "phase_for_step",
    "current_step",
    "derive_current_action",
]

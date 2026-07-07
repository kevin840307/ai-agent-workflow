from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.paths import utc_now, write_text
from app.workflow_runtime.failure_classifier import classify_failure

REPAIR_SCHEMA = "aiwf.small-model-repair-policy.v1"

_SMALL_MODEL_POLICIES: dict[str, dict[str, str]] = {
    "NO_FILE_CHANGE": {
        "retry_target_hint": "same implementation step",
        "prompt_mode": "short_direct_edit",
        "instruction": "直接修改指定專案檔案。不要只回覆說明、計畫、Markdown 或工具 JSON。完成後列出實際改過的檔案。",
    },
    "INVALID_OUTPUT": {
        "retry_target_hint": "same step",
        "prompt_mode": "format_repair",
        "instruction": "不要輸出 write_file/edit_file JSON 或 FILE block。請使用 CLI/agent 的實際檔案編輯能力，或回傳該 step 需要的有效 JSON/Markdown artifact。",
    },
    "TEST_FAILED": {
        "retry_target_hint": "build",
        "prompt_mode": "test_failure_repair",
        "instruction": "以測試 stdout/stderr 為唯一修復依據，優先修 production code；只有測試明顯錯誤時才改 tests。",
    },
    "VALIDATION_FAILED": {
        "retry_target_hint": "build",
        "prompt_mode": "validation_oracle_repair",
        "instruction": "validation.py 是驗收準則。請根據 validation stdout/stderr 修 production output，直到 validation exit code 為 0。",
    },
    "PROJECT_GUARD_BLOCKED": {
        "retry_target_hint": "same step",
        "prompt_mode": "path_scope_repair",
        "instruction": "所有寫入都必須在 Project Path 內，使用相對路徑，不要嘗試修改外部資料夾。",
    },
    "TIMEOUT": {
        "retry_target_hint": "same step or replan",
        "prompt_mode": "scope_reduction",
        "instruction": "縮小任務，只做當前 step 必要修改；避免長時間命令、網路下載、大型掃描。",
    },
    "EXPECTED_FILES_MISSING": {
        "retry_target_hint": "producer step",
        "prompt_mode": "expected_file_repair",
        "instruction": "依 step contract 建立缺少的 expected files，路徑與檔名必須完全一致。",
    },
    "AGENT_EMPTY_OUTPUT": {
        "retry_target_hint": "same step",
        "prompt_mode": "minimal_prompt_retry",
        "instruction": "用最短 prompt 重新要求執行一個具體檔案修改，並確認 agent command 設定可用。",
    },
    "UNKNOWN": {
        "retry_target_hint": "manual inspection",
        "prompt_mode": "evidence_review",
        "instruction": "先查看 run-log、step artifacts、validation/test output，再決定 retry target。",
    },
}


def policy_for_failure(message: Any = None, *, step_key: str | None = None, error_code: str | None = None, retry_count: int = 0) -> dict[str, Any]:
    failure = classify_failure(message, step_key=step_key, error_code=error_code)
    base = _SMALL_MODEL_POLICIES.get(failure.get("code") or "UNKNOWN") or _SMALL_MODEL_POLICIES["UNKNOWN"]
    escalation = None
    if retry_count >= 3 and failure.get("code") in {"NO_FILE_CHANGE", "INVALID_OUTPUT", "TIMEOUT", "UNKNOWN"}:
        escalation = "replan_or_split_task"
    elif retry_count >= 3:
        escalation = "try_different_implementation_approach"
    return {
        "schema": REPAIR_SCHEMA,
        "generated_at": utc_now(),
        "failure": failure,
        "retry_count": retry_count,
        "retry_target_hint": base["retry_target_hint"],
        "prompt_mode": base["prompt_mode"],
        "repair_instruction": base["instruction"],
        "escalation": escalation,
    }


def render_repair_prompt(policy: dict[str, Any]) -> str:
    failure = policy.get("failure") or {}
    lines = [
        "### Small Model Repair Policy",
        f"- Failure: {failure.get('code')} - {failure.get('title')}",
        f"- Retry target hint: {policy.get('retry_target_hint')}",
        f"- Prompt mode: {policy.get('prompt_mode')}",
        f"- Instruction: {policy.get('repair_instruction')}",
    ]
    if policy.get("escalation"):
        lines.append(f"- Escalation: {policy.get('escalation')}")
    return "\n".join(lines).rstrip() + "\n"


def write_repair_policy_artifact(run: dict[str, Any], step_key: str, message: Any, *, error_code: str | None = None, retry_count: int = 0) -> dict[str, Any]:
    policy = policy_for_failure(message, step_key=step_key, error_code=error_code, retry_count=retry_count)
    run_dir = Path(run["workspace"])
    out = run_dir / ".workflow" / "repair-policy"
    out.mkdir(parents=True, exist_ok=True)
    safe_key = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(step_key or "run"))
    write_text(out / f"{safe_key}.json", json.dumps(policy, indent=2, ensure_ascii=False))
    write_text(out / f"{safe_key}.md", render_repair_prompt(policy))
    return policy


__all__ = ["REPAIR_SCHEMA", "policy_for_failure", "render_repair_prompt", "write_repair_policy_artifact"]

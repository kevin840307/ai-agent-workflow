#!/usr/bin/env python3
"""Run the repository test suite in deterministic groups.

A single long pytest process can keep FastAPI TestClient background state and
asyncio event-loop resources alive across unrelated workflow tests. The grouped
runner covers every test module while giving each group a clean interpreter and
isolated store file.
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = REPO_ROOT / "test-results"
PYTEST_GROUPS: list[tuple[str, list[str]]] = [
    (
        "A_core_cli_api",
        [
            "tests/test_agent_runner.py",
            "tests/test_ai_workflow_assets_ui.py",
            "tests/test_aiwf_cli.py",
            "tests/test_api_smoke.py",
            "tests/test_auto_workflow_orchestrator.py",
            "tests/test_controller_observability_and_manual_controls.py",
            "tests/test_controller_productization.py",
        ],
    ),
    (
        "B_general_project_prompt",
        [
            "tests/test_general_auto_development_workflow.py",
            "tests/test_large_project_fixture.py",
            "tests/test_project_and_config_api.py",
            "tests/test_prompt_builder.py",
            "tests/test_python_functions_multi.py",
        ],
    ),
    (
        "C_manual_run_state",
        [
            "tests/test_real_qwen_workflow_manual.py",
            "tests/test_release_and_ui_manual.py",
            "tests/test_run_state.py",
        ],
    ),
    (
        "D_runtime_safety_contracts",
        [
            "tests/test_runtime_files_and_qwen.py",
            "tests/test_runtime_refactor_contract.py",
            "tests/test_runtime_safety.py",
            "tests/test_static_architecture_contract.py",
        ],
    ),
    (
        "E_workflow_assets_stability",
        [
            "tests/test_workflow_advanced_stability.py",
            "tests/test_workflow_assets.py",
            "tests/test_workflow_assets_functional_e2e.py",
            "tests/test_workflow_config_service.py",
        ],
    ),
    (
        "F_workflow_e2e_contracts",
        [
            "tests/test_workflow_core.py",
            "tests/test_workflow_function_refactor_contract.py",
            "tests/test_workflow_functions.py",
            "tests/test_workflow_integration.py",
            "tests/test_workflow_non_e2e_contracts.py",
            "tests/test_workflow_quality_contracts.py",
            "tests/test_workflow_resilience_e2e.py",
        ],
    ),
]


def _reset_group_state(group_name: str) -> None:
    pytest_data = REPO_ROOT / "data" / "pytest"
    shutil.rmtree(pytest_data, ignore_errors=True)
    pytest_data.mkdir(parents=True, exist_ok=True)
    (pytest_data / ".group").write_text(group_name, encoding="utf-8")


def _env_for_group(group_name: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    env["AIWF_STORE_FILE"] = str(REPO_ROOT / "data" / "pytest" / f"store-{group_name}.json")
    env.setdefault("QWEN_USE_SERVE", "0")
    env.setdefault("QWEN_WORKFLOW_SHOW_AGENT_STDOUT", "0")
    # These real-agent scenarios are opt-in. The normal test suite should stay mock/local.
    env.pop("RUN_REAL_QWEN", None)
    env.pop("RUN_REAL_QWEN_FULL", None)
    env.pop("RUN_REAL_QWEN_STABILITY", None)
    env.pop("RUN_CLEAN_REPO_SMOKE", None)
    env.pop("RUN_PLAYWRIGHT_UI", None)
    return env


def _tail(text: str, max_lines: int = 40) -> str:
    lines = text.rstrip().splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(["...", *lines[-max_lines:]])


def run_group(group_name: str, test_files: list[str], timeout_seconds: int) -> int:
    _reset_group_state(group_name)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{group_name}.log"
    cmd = [sys.executable, "-m", "pytest", "-q", *test_files]
    start = time.monotonic()
    timed_out = False
    with log_path.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            env=_env_for_group(group_name),
            text=True,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return_code = proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=5)
            except Exception:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    pass
                proc.wait(timeout=5)
            return_code = 124
            log_file.write(f"\nTIMEOUT after {timeout_seconds} seconds\n")

    elapsed = time.monotonic() - start
    output = log_path.read_text(encoding="utf-8", errors="replace")
    print(f"\n=== {group_name} ({elapsed:.1f}s) ===")
    print(_tail(output))
    if return_code != 0:
        suffix = " timed out" if timed_out else " failed"
        print(f"Group {group_name}{suffix}. See {log_path}", file=sys.stderr)
    return return_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Run all tests in deterministic groups.")
    parser.add_argument("--group-timeout", type=int, default=180, help="timeout seconds per group")
    args = parser.parse_args()

    failures: list[str] = []
    started = time.monotonic()
    for group_name, test_files in PYTEST_GROUPS:
        rc = run_group(group_name, test_files, args.group_timeout)
        if rc != 0:
            failures.append(group_name)
            break

    elapsed = time.monotonic() - started
    failed_index = None
    if failures:
        failed_index = next(
            index for index, (group_name, _files) in enumerate(PYTEST_GROUPS) if group_name == failures[0]
        )
    groups_run = len(PYTEST_GROUPS) if failed_index is None else failed_index + 1
    group_lines = []
    for index, (group_name, _files) in enumerate(PYTEST_GROUPS):
        if failed_index is not None and index > failed_index:
            state = "not run"
        elif group_name in failures:
            state = "failed"
        else:
            state = "see log"
        group_lines.append(f"- {group_name}: {state}")

    summary = [
        f"status: {'PASS' if not failures else 'FAIL'}",
        f"elapsed_seconds: {elapsed:.1f}",
        f"groups_run: {groups_run}",
        f"failures: {', '.join(failures) if failures else 'none'}",
        "",
        "groups:",
        *group_lines,
    ]
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / "summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n" + "\n".join(summary))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

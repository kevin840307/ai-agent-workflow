#!/usr/bin/env python3
"""Run the repository test suite in deterministic groups.

Why this exists:
- Unit/integration/e2e tests use FastAPI TestClient and workflow background tasks.
- A single long pytest interpreter can keep event-loop/TestClient state alive across
  unrelated workflow tests and make the full suite look hung even when individual
  files pass.
- This runner gives each group a clean interpreter, isolated store, and explicit
  timeout while verifying that every tests/test_*.py file is covered by a group.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = REPO_ROOT / "test-results"
TEST_RUN_ID = f"{int(time.time())}-{os.getpid()}"

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
            "tests/test_isolated_workspace.py",
            "tests/test_large_project_fixture.py",
            "tests/test_project_and_config_api.py",
            "tests/test_prompt_builder.py",
            "tests/test_python_functions_multi.py",
        ],
    ),
    (
        "C_productization_features",
        [
            "tests/test_next_round_features.py",
            "tests/test_practical_platform_features.py",
            "tests/test_test_pipeline_and_lifecycle.py",
            "tests/test_productization_next_features.py",
        ],
    ),
    (
        "D_manual_run_state",
        [
            "tests/test_real_qwen_workflow_manual.py",
            "tests/test_release_and_ui_manual.py",
            "tests/test_run_state.py",
        ],
    ),
    (
        "E_runtime_safety_contracts",
        [
            "tests/test_runtime_files_and_qwen.py",
            "tests/test_runtime_refactor_contract.py",
            "tests/test_runtime_safety.py",
            "tests/test_static_architecture_contract.py",
            "tests/test_supervisor_patch_defaults_and_action_split.py",
            "tests/test_hardening_next.py",
            "tests/test_production_hardening_round2.py",
            "tests/test_production_hardening_round3.py",
            "tests/test_full_system_optimization_round4.py",
        ],
    ),
    (
        "F_workflow_assets_stability",
        [
            "tests/test_workflow_advanced_stability.py",
            "tests/test_workflow_assets.py",
            "tests/test_workflow_assets_functional_e2e.py",
            "tests/test_workflow_config_service.py",
        ],
    ),
    ("G_self_prompt_e2e", ["tests/test_self_prompt_workflow_e2e.py"]),
    (
        "H_workflow_core_contracts",
        [
            "tests/test_workflow_core.py",
            "tests/test_workflow_function_refactor_contract.py",
            "tests/test_workflow_functions.py",
        ],
    ),
    ("I_workflow_integration", ["tests/test_workflow_integration.py"]),
    (
        "J_workflow_quality_resilience",
        [
            "tests/test_workflow_non_e2e_contracts.py",
            "tests/test_workflow_quality_contracts.py",
            "tests/test_workflow_resilience_e2e.py",
        ],
    ),
]

FAST_GROUPS = {"A_core_cli_api", "B_general_project_prompt", "C_productization_features", "D_manual_run_state"}
E2E_GROUPS = {
    "E_runtime_safety_contracts",
    "F_workflow_assets_stability",
    "G_self_prompt_e2e",
    "H_workflow_core_contracts",
    "I_workflow_integration",
    "J_workflow_quality_resilience",
}


def discover_test_files() -> list[str]:
    return sorted(path.relative_to(REPO_ROOT).as_posix() for path in (REPO_ROOT / "tests").glob("test_*.py"))


def grouped_test_files() -> list[str]:
    return [item for _group_name, files in PYTEST_GROUPS for item in files]


def coverage_report() -> dict[str, object]:
    discovered = set(discover_test_files())
    grouped = grouped_test_files()
    grouped_set = set(grouped)
    duplicates = sorted({item for item in grouped if grouped.count(item) > 1})
    missing = sorted(discovered - grouped_set)
    extra = sorted(grouped_set - discovered)
    return {
        "schema": "aiwf.test-pipeline-coverage.v1",
        "discovered_count": len(discovered),
        "grouped_count": len(grouped_set),
        "missing": missing,
        "extra": extra,
        "duplicates": duplicates,
        "ok": not missing and not extra and not duplicates,
    }


def selected_groups(mode: str) -> list[tuple[str, list[str]]]:
    if mode == "fast":
        return [(name, files) for name, files in PYTEST_GROUPS if name in FAST_GROUPS]
    if mode == "e2e":
        return [(name, files) for name, files in PYTEST_GROUPS if name in E2E_GROUPS]
    return PYTEST_GROUPS


def _group_state_dir(group_name: str) -> Path:
    return REPO_ROOT / "data" / "pytest" / TEST_RUN_ID / group_name


def _reset_group_state(group_name: str) -> None:
    pytest_data = _group_state_dir(group_name)
    shutil.rmtree(pytest_data, ignore_errors=True)
    pytest_data.mkdir(parents=True, exist_ok=True)
    (pytest_data / ".group").write_text(group_name, encoding="utf-8")


def _env_for_group(group_name: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    env["AIWF_STORE_FILE"] = str(_group_state_dir(group_name) / "store.json")
    env.setdefault("QWEN_USE_SERVE", "0")
    env.setdefault("QWEN_WORKFLOW_SHOW_AGENT_STDOUT", "0")
    # These real-agent/manual scenarios are opt-in. The normal test suite stays mock/local.
    for key in [
        "RUN_REAL_QWEN",
        "RUN_REAL_QWEN_FULL",
        "RUN_REAL_QWEN_STABILITY",
        "RUN_CLEAN_REPO_SMOKE",
        "RUN_PLAYWRIGHT_UI",
    ]:
        env.pop(key, None)
    return env


def _tail(text: str, max_lines: int = 40) -> str:
    lines = text.rstrip().splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(["...", *lines[-max_lines:]])


def _terminate_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return
        time.sleep(0.05)
    try:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_pytest(label: str, test_files: list[str], timeout_seconds: int, *, extra_args: list[str] | None = None) -> dict[str, object]:
    _reset_group_state(label)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{label}.log"
    cmd = [sys.executable, "-m", "pytest", "-q", "--durations=20", *(extra_args or []), *test_files]
    start = time.monotonic()
    timed_out = False
    return_code = 0
    with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
        process = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            env=_env_for_group(label),
            text=True,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=(os.name != "nt"),
        )
        while True:
            return_code = process.poll()
            if return_code is not None:
                break
            if time.monotonic() - start > timeout_seconds:
                timed_out = True
                log_file.write(f"\nTIMEOUT after {timeout_seconds} seconds\n")
                log_file.flush()
                _terminate_process_tree(process)
                return_code = 124
                break
            time.sleep(0.1)
    elapsed = time.monotonic() - start
    output = log_path.read_text(encoding="utf-8", errors="replace")
    print(f"\n=== {label} ({elapsed:.1f}s) ===", flush=True)
    print(_tail(output), flush=True)
    if return_code != 0:
        suffix = " timed out" if timed_out else " failed"
        print(f"Group {label}{suffix}. See {log_path}", file=sys.stderr, flush=True)
    return {
        "name": label,
        "return_code": return_code,
        "elapsed_seconds": round(elapsed, 2),
        "timed_out": timed_out,
        "log": str(log_path.relative_to(REPO_ROOT)),
        "files": test_files,
    }

def isolate_group_files(group_name: str, test_files: list[str], timeout_seconds: int) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for test_file in test_files:
        safe_name = Path(test_file).stem
        results.append(run_pytest(f"{group_name}__{safe_name}", [test_file], timeout_seconds))
    return results


def group_by_name(name: str) -> tuple[str, list[str]] | None:
    return next(((group_name, files) for group_name, files in PYTEST_GROUPS if group_name == name), None)


def exec_single_group(group_name: str) -> None:
    group = group_by_name(group_name)
    if group is None:
        available = ", ".join(name for name, _files in PYTEST_GROUPS)
        raise SystemExit(f"Unknown group: {group_name}. Available groups: {available}")
    _reset_group_state(group_name)
    _name, files = group
    env = _env_for_group(group_name)
    os.execvpe(sys.executable, [sys.executable, "-m", "pytest", "-q", "--durations=20", *files], env)


def write_shell_pipeline(groups: list[tuple[str, list[str]]], group_timeout: int) -> Path:
    """Write a POSIX shell pipeline that runs groups without a long-lived Python parent.

    Some workflow subprocess tests can leave interpreter shutdown state that makes
    a second pytest child hang only when launched from the same Python parent.
    Replacing the parent with bash gives the CI command one entry point while
    preserving one fresh Python interpreter per pytest group.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    script_path = LOG_DIR / "run-groups.sh"
    lines = [
        "#!/usr/bin/env bash",
        "set -u",
        f"cd {shlex.quote(str(REPO_ROOT))}",
        f"mkdir -p {shlex.quote(str(LOG_DIR))}",
        "STATUS=0",
        f"SUMMARY={shlex.quote(str(LOG_DIR / 'summary.txt'))}",
        "echo 'status: RUNNING' > \"$SUMMARY\"",
        f"echo 'coverage_ok: true' >> \"$SUMMARY\"",
        "echo '' >> \"$SUMMARY\"",
        "echo 'groups:' >> \"$SUMMARY\"",
    ]
    for group_name, files in groups:
        log_path = LOG_DIR / f"{group_name}.log"
        store_path = _group_state_dir(group_name) / "store.json"
        store_path.parent.mkdir(parents=True, exist_ok=True)
        file_args = " ".join(shlex.quote(item) for item in files)
        cmd = (
            f"PYTHONPATH={shlex.quote(str(REPO_ROOT))} "
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 "
            f"AIWF_STORE_FILE={shlex.quote(str(store_path))} "
            "QWEN_USE_SERVE=0 QWEN_WORKFLOW_SHOW_AGENT_STDOUT=0 "
            f"{shlex.quote(sys.executable)} -m pytest -q --durations=20 {file_args}"
        )
        lines.extend(
            [
                f"echo ''",
                f"echo '=== {group_name} ==='",
                f"echo '=== {group_name} ===' > {shlex.quote(str(log_path))}",
                f"timeout {int(group_timeout)} bash -lc {shlex.quote(cmd)} >> {shlex.quote(str(log_path))} 2>&1",
                "RC=$?",
                f"tail -40 {shlex.quote(str(log_path))}",
                "if [ \"$RC\" -ne 0 ]; then",
                f"  echo '- {group_name}: FAIL rc='\"$RC\"' log={log_path.relative_to(REPO_ROOT).as_posix()}' >> \"$SUMMARY\"",
                "  STATUS=$RC",
                "  break",
                "else",
                f"  echo '- {group_name}: PASS log={log_path.relative_to(REPO_ROOT).as_posix()}' >> \"$SUMMARY\"",
                "fi",
            ]
        )
    lines.extend(
        [
            "if [ \"$STATUS\" -eq 0 ]; then",
            "  sed -i '1s/.*/status: PASS/' \"$SUMMARY\"",
            "else",
            "  sed -i '1s/.*/status: FAIL/' \"$SUMMARY\"",
            "fi",
            "echo ''",
            "cat \"$SUMMARY\"",
            "exit \"$STATUS\"",
        ]
    )
    script_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    script_path.chmod(0o755)
    return script_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run all tests in deterministic groups.")
    parser.add_argument("--mode", choices=["all", "fast", "e2e"], default="all", help="test subset to run")
    parser.add_argument("--group", help="run one deterministic test group and exec directly into pytest")
    parser.add_argument("--list-groups", action="store_true", help="print available test groups and exit")
    parser.add_argument("--group-timeout", type=int, default=240, help="timeout seconds per group")
    parser.add_argument("--file-timeout", type=int, default=180, help="timeout seconds per isolated file fallback")
    parser.add_argument("--no-isolate-on-failure", action="store_true", help="do not rerun failed/timeout group file-by-file")
    parser.add_argument("--strict-coverage", action="store_true", default=True, help="fail if a tests/test_*.py file is not assigned to a group")
    parser.add_argument("--no-strict-coverage", dest="strict_coverage", action="store_false")
    parser.add_argument("--python-runner", action="store_true", help="use the in-process Python group launcher instead of the generated shell pipeline")
    parser.add_argument("--execute-all", action="store_true", help="run all selected groups sequentially; CI should prefer --group matrix jobs")
    args = parser.parse_args()

    if args.list_groups:
        for group_name, files in PYTEST_GROUPS:
            print(f"{group_name}: {' '.join(files)}")
        return 0
    if args.group:
        exec_single_group(args.group)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    coverage = coverage_report()
    (LOG_DIR / "coverage.json").write_text(json.dumps(coverage, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.strict_coverage and not coverage["ok"]:
        print(json.dumps(coverage, indent=2, ensure_ascii=False), file=sys.stderr)
        return 2

    failures: list[str] = []
    group_results: list[dict[str, object]] = []
    isolated_results: dict[str, list[dict[str, object]]] = {}
    started = time.monotonic()
    groups = selected_groups(args.mode)
    if not args.execute_all:
        commands = [f"python scripts/run_tests.py --group {group_name}" for group_name, _files in groups]
        lines = [
            "status: PLAN",
            f"mode: {args.mode}",
            f"coverage_ok: {coverage['ok']} ({coverage['grouped_count']}/{coverage['discovered_count']} files)",
            "",
            "Run these CI matrix commands:",
            *commands,
        ]
        (LOG_DIR / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        return 0
    if os.name != "nt" and not args.python_runner:
        script_path = write_shell_pipeline(groups, args.group_timeout)
        os.execv("/bin/bash", ["bash", str(script_path)])
    for group_name, test_files in groups:
        result = run_pytest(group_name, test_files, args.group_timeout)
        group_results.append(result)
        if result["return_code"] != 0:
            failures.append(group_name)
            if not args.no_isolate_on_failure:
                isolated = isolate_group_files(group_name, test_files, args.file_timeout)
                isolated_results[group_name] = isolated
            break

    elapsed = time.monotonic() - started
    summary = {
        "schema": "aiwf.test-pipeline.v2",
        "status": "PASS" if not failures else "FAIL",
        "mode": args.mode,
        "elapsed_seconds": round(elapsed, 2),
        "coverage": coverage,
        "groups_run": len(group_results),
        "failures": failures,
        "group_results": group_results,
        "isolated_results": isolated_results,
    }
    (LOG_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        f"status: {summary['status']}",
        f"mode: {args.mode}",
        f"elapsed_seconds: {elapsed:.1f}",
        f"groups_run: {len(group_results)}",
        f"failures: {', '.join(failures) if failures else 'none'}",
        f"coverage_ok: {coverage['ok']} ({coverage['grouped_count']}/{coverage['discovered_count']} files)",
        "",
        "groups:",
    ]
    for result in group_results:
        status = "PASS" if result["return_code"] == 0 else "FAIL"
        lines.append(f"- {result['name']}: {status}, rc={result['return_code']}, elapsed={result['elapsed_seconds']}s, log={result['log']}")
    if isolated_results:
        lines.append("")
        lines.append("isolated fallback:")
        for group_name, results in isolated_results.items():
            lines.append(f"- {group_name}:")
            for item in results:
                status = "PASS" if item["return_code"] == 0 else "FAIL"
                lines.append(f"  - {item['name']}: {status}, rc={item['return_code']}, log={item['log']}")
    (LOG_DIR / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

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
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.agents.process_supervisor import terminate_popen_tree
LOG_DIR = REPO_ROOT / "test-results"
TEST_RUN_ID = f"{int(time.time())}-{os.getpid()}"

from app.testing.test_catalog import (
    E2E_GROUPS,
    FAST_GROUPS,
    PROFILE_TIERS,
    PYTEST_GROUPS,
    TEST_TIERS,
    groups_for_profile,
)


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


def selected_groups(mode: str, tier: str | None = None, profile: str | None = None) -> list[tuple[str, list[str]]]:
    if profile:
        return groups_for_profile(profile)
    if tier:
        names = TEST_TIERS.get(tier)
        if names is None:
            available = ", ".join(sorted(TEST_TIERS))
            raise SystemExit(f"Unknown tier: {tier}. Available tiers: {available}")
        return [(name, files) for name, files in PYTEST_GROUPS if name in names]
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
        "RUN_REAL_QWEN_UNATTENDED",
        "RUN_REAL_QWEN_UNATTENDED_PARALLEL",
    ]:
        env.pop(key, None)
    return env


def _tail(text: str, max_lines: int = 40) -> str:
    lines = text.rstrip().splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(["...", *lines[-max_lines:]])


def _console_safe(text: str) -> str:
    """Keep UTF-8 logs intact while tolerating legacy Windows consoles."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="backslashreplace").decode(encoding)


def _terminate_process_tree(process: subprocess.Popen) -> None:
    terminate_popen_tree(process, grace_sec=2.0)


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
    print(_console_safe(_tail(output)), flush=True)
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



def _junit_totals(paths: list[Path]) -> dict[str, int]:
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for path in paths:
        if not path.exists():
            continue
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
        for suite in suites:
            for key in totals:
                totals[key] += int(suite.attrib.get(key, "0") or 0)
    totals["passed"] = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    return totals


def _junit_slowest(paths: list[Path], limit: int = 30) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for path in paths:
        if not path.exists():
            continue
        root = ET.parse(path).getroot()
        for case in root.iter("testcase"):
            cases.append({
                "name": case.attrib.get("name", ""),
                "classname": case.attrib.get("classname", ""),
                "seconds": round(float(case.attrib.get("time", "0") or 0), 4),
                "junit": str(path.relative_to(REPO_ROOT)),
            })
    return sorted(cases, key=lambda item: float(item["seconds"]), reverse=True)[:limit]


def run_isolated_matrix(groups: list[tuple[str, list[str]]], file_timeout: int, *, profile: str | None = None) -> int:
    """Run every test file in a fresh interpreter and aggregate JUnit evidence.

    This is the production acceptance path. It avoids FastAPI/TestClient or agent
    subprocess teardown state leaking from one test module into another while
    still executing the complete assigned matrix.
    """
    junit_dir = LOG_DIR / "junit"
    shutil.rmtree(junit_dir, ignore_errors=True)
    junit_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    junit_paths: list[Path] = []
    started = time.monotonic()
    for group_name, files in groups:
        for test_file in files:
            stem = Path(test_file).stem
            label = f"{group_name}__{stem}"
            junit_path = junit_dir / f"{label}.xml"
            junit_paths.append(junit_path)
            result = run_pytest(label, [test_file], file_timeout, extra_args=[f"--junitxml={junit_path}"])
            results.append(result)
    failures = [str(item["name"]) for item in results if int(item["return_code"]) != 0]
    totals = _junit_totals(junit_paths)
    slowest = _junit_slowest(junit_paths)
    coverage = coverage_report()
    summary = {
        "schema": "aiwf.test-pipeline.v3",
        "status": "PASS" if not failures else "FAIL",
        "mode": "isolated-all",
        "profile": profile,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "coverage": coverage,
        "files_run": len(results),
        "failures": failures,
        "junit_totals": totals,
        "slowest_tests": slowest,
        "results": results,
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (LOG_DIR / "slowest-tests.json").write_text(json.dumps({"schema": "aiwf.slowest-tests.v1", "tests": slowest}, indent=2, ensure_ascii=False), encoding="utf-8")
    (LOG_DIR / "release-test-manifest.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        f"status: {summary['status']}",
        "mode: isolated-all",
        f"elapsed_seconds: {summary['elapsed_seconds']}",
        f"files_run: {summary['files_run']}",
        f"coverage_ok: {coverage['ok']} ({coverage['grouped_count']}/{coverage['discovered_count']} files)",
        f"tests: {totals['tests']}",
        f"passed: {totals['passed']}",
        f"skipped: {totals['skipped']}",
        f"failures: {totals['failures']}",
        f"errors: {totals['errors']}",
        f"failed_files: {', '.join(failures) if failures else 'none'}",
    ]
    (LOG_DIR / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines), flush=True)
    return 1 if failures else 0

def main() -> int:
    parser = argparse.ArgumentParser(description="Run all tests in deterministic groups.")
    parser.add_argument("--mode", choices=["all", "fast", "e2e"], default="all", help="test subset to run")
    parser.add_argument("--profile", choices=sorted(PROFILE_TIERS), help="named pipeline: developer, commit, release, or e2e")
    parser.add_argument("--tier", choices=sorted(TEST_TIERS), help="run a stability tier: unit, contract, integration, e2e, or soak")
    parser.add_argument("--group", help="run one deterministic test group and exec directly into pytest")
    parser.add_argument("--list-groups", action="store_true", help="print available test groups and exit")
    parser.add_argument("--group-timeout", type=int, default=240, help="timeout seconds per group")
    parser.add_argument("--file-timeout", type=int, default=180, help="timeout seconds per isolated file fallback")
    parser.add_argument("--no-isolate-on-failure", action="store_true", help="do not rerun failed/timeout group file-by-file")
    parser.add_argument("--strict-coverage", action="store_true", default=True, help="fail if a tests/test_*.py file is not assigned to a group")
    parser.add_argument("--no-strict-coverage", dest="strict_coverage", action="store_false")
    parser.add_argument("--python-runner", action="store_true", help="use the in-process Python group launcher instead of the generated shell pipeline")
    parser.add_argument("--execute-all", action="store_true", help="run all selected groups sequentially; CI should prefer --group matrix jobs")
    parser.add_argument("--isolate-all", action="store_true", help="run every selected test file in its own pytest interpreter and aggregate JUnit evidence")
    args = parser.parse_args()

    if args.profile == "release":
        args.isolate_all = True
    elif args.profile:
        args.execute_all = True
        args.python_runner = True

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
    groups = selected_groups(args.mode, args.tier, args.profile)
    if args.isolate_all:
        return run_isolated_matrix(groups, args.file_timeout, profile=args.profile)
    if not args.execute_all:
        commands = [f"python scripts/run_tests.py --group {group_name}" for group_name, _files in groups]
        lines = [
            "status: PLAN",
            f"mode: {args.mode}",
            f"profile: {args.profile or 'none'}",
            f"tier: {args.tier or 'none'}",
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
        "profile": args.profile,
        "elapsed_seconds": round(elapsed, 2),
        "coverage": coverage,
        "groups_run": len(group_results),
        "failures": failures,
        "group_results": group_results,
        "isolated_results": isolated_results,
    }
    (LOG_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    slowest_groups = sorted(
        ({"name": item["name"], "seconds": item["elapsed_seconds"], "log": item["log"]} for item in group_results),
        key=lambda item: float(item["seconds"]),
        reverse=True,
    )
    (LOG_DIR / "slowest-tests.json").write_text(json.dumps({"schema": "aiwf.slowest-groups.v1", "groups": slowest_groups}, indent=2, ensure_ascii=False), encoding="utf-8")
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

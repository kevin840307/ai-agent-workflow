#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES_ROOT = ROOT / "examples" / "real_qwen_cases"
TERMINAL_STATUS = {"done", "failed", "cancelled", "waiting_input"}


def _case_dirs(root: Path) -> list[Path]:
    return [path for path in sorted(root.iterdir()) if path.is_dir() and (path / "case.json").exists()]


def _load_case(path: Path) -> dict[str, Any]:
    meta = json.loads((path / "case.json").read_text(encoding="utf-8"))
    prompt = (path / "prompt.txt").read_text(encoding="utf-8").strip()
    if not prompt or "\n" in prompt:
        raise ValueError(f"{path.name}/prompt.txt 必須是一行非空 Prompt")
    validation = path / "validation.py"
    if not validation.exists():
        raise ValueError(f"{path.name} 缺少 validation.py")
    return {"dir": path, "id": meta.get("id") or path.name, "meta": meta, "prompt": prompt}


def _copy_case_project(case: dict[str, Any], project: Path) -> None:
    if project.exists():
        shutil.rmtree(project)
    seed = case["dir"] / "project_seed"
    if seed.exists():
        shutil.copytree(seed, project)
    else:
        project.mkdir(parents=True)
    shutil.copy2(case["dir"] / "validation.py", project / "validation.py")


def _snapshot(project: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(project.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(project).as_posix()
        if rel.startswith(".ai-workflow/") or rel == "validation.py" or "__pycache__" in path.parts:
            continue
        result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _extract_json(stdout: str) -> dict[str, Any]:
    raw = stdout.strip()
    if not raw:
        raise ValueError("CLI stdout 是空的")
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, char in enumerate(stdout):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append(value)
    if not candidates:
        raise ValueError("CLI stdout 找不到 JSON Run 結果")
    run_candidates = [item for item in candidates if item.get("id") and item.get("status") and isinstance(item.get("steps"), list)]
    return run_candidates[0] if run_candidates else candidates[0]


def _retry_count(run: dict[str, Any]) -> int:
    return sum(int(step.get("retry_count") or 0) for step in run.get("steps") or [])


def _validation_status(run: dict[str, Any]) -> str:
    results = run.get("validation_results") or run.get("validation") or []
    if isinstance(results, dict):
        values = list(results.values())
    else:
        values = list(results) if isinstance(results, list) else []
    statuses = {str(item.get("status") or "").upper() for item in values if isinstance(item, dict)}
    if "FAIL" in statuses or "FAILED" in statuses or "ERROR" in statuses or "BLOCKED" in statuses:
        return "FAIL"
    if "PASS" in statuses or "PASSED" in statuses:
        return "PASS"
    return "UNKNOWN"


def _run_validation(project: Path, timeout_sec: float) -> dict[str, Any]:
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "validation.py"],
        cwd=project,
        text=True,
        capture_output=True,
        timeout=timeout_sec,
    )
    return {
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "exit_code": proc.returncode,
        "duration_sec": round(time.monotonic() - started, 3),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _write_markdown(output: Path, aggregate: dict[str, Any]) -> None:
    lines = [
        "# Local Real-Agent Case Report",
        "",
        f"- Agent: {aggregate['agent']}",
        f"- Workflow: {aggregate['workflow']}",
        f"- Result: {aggregate['status']}",
        f"- Passed: {aggregate['passed']}",
        f"- Failed: {aggregate['failed']}",
        "",
        "| Case | Result | Run | Validation | Retries | Duration | Changed files |",
        "|---|---|---|---|---:|---:|---|",
    ]
    for item in aggregate["results"]:
        lines.append(
            f"| {item['case']} | {item['status']} | {item.get('run_status', '-')} | "
            f"{item.get('validation_status', '-')} | {item.get('retries', 0)} | "
            f"{item.get('duration_sec', 0)}s | {', '.join(item.get('changed_files') or []) or '-'} |"
        )
    (output / "report.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="在本機以真實 Qwen/OpenCode 執行單行 Prompt Case Library。")
    parser.add_argument("--agent", choices=["qwen", "opencode"], default="qwen")
    parser.add_argument("--workflow", choices=["general-auto-development", "adaptive-auto-workflow"], default="general-auto-development")
    parser.add_argument("--case", action="append", dest="cases", help="Case ID，可重複；省略或使用 all 會執行全部。")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout-sec", type=float, default=900)
    parser.add_argument("--validation-timeout-sec", type=float, default=120)
    parser.add_argument("--output", default="reports/local-real-agent-cases")
    parser.add_argument("--cases-root", default=str(DEFAULT_CASES_ROOT))
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-mock", action="store_true")
    args = parser.parse_args()

    cases_root = Path(args.cases_root).resolve()
    available = {case["id"]: case for case in (_load_case(path) for path in _case_dirs(cases_root))}
    if args.list:
        print(json.dumps({"cases": [{"id": cid, "title": item["meta"].get("title"), "prompt": item["prompt"]} for cid, item in available.items()]}, indent=2, ensure_ascii=False))
        return 0

    requested = args.cases or ["all"]
    selected_ids = list(available) if "all" in requested else requested
    missing = [case_id for case_id in selected_ids if case_id not in available]
    if missing:
        parser.error(f"Unknown case(s): {', '.join(missing)}")
    if args.repeat < 1:
        parser.error("--repeat 必須大於 0")

    mock_enabled = os.environ.get("QWEN_MOCK") == "1"
    if mock_enabled and not args.allow_mock and not args.dry_run:
        parser.error("目前 QWEN_MOCK=1；真實測試請先移除，或明確使用 --allow-mock。")
    if not args.dry_run and not mock_enabled and shutil.which(args.agent) is None:
        parser.error(f"找不到 {args.agent} CLI，請先安裝並確認可從 PATH 執行。")

    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    launcher = ROOT / "scripts" / "aiwf_agent_command.py"
    results: list[dict[str, Any]] = []

    for case_id in selected_ids:
        case = available[case_id]
        for attempt in range(1, args.repeat + 1):
            label = case_id if args.repeat == 1 else f"{case_id}-run-{attempt:02d}"
            case_output = output / label
            project = case_output / "project"
            case_output.mkdir(parents=True, exist_ok=True)
            _copy_case_project(case, project)
            before = _snapshot(project)
            command = [
                sys.executable, str(launcher), "run",
                "--project", str(project),
                "--workflow", args.workflow,
                "--agent", args.agent,
                "--profile", "fast",
                "--thinking-level", "medium",
                "--validation-script", "validation.py",
                "--test-command", f'"{sys.executable}" validation.py',
                "--wait", "--json",
                case["prompt"],
            ]
            plan = {"case": case_id, "attempt": attempt, "prompt": case["prompt"], "project": str(project), "command": command}
            (case_output / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            if args.dry_run:
                results.append({"case": label, "status": "DRY_RUN", "prompt": case["prompt"], "changed_files": []})
                continue

            env = os.environ.copy()
            env.setdefault("QWEN_USE_SERVE", "0")
            env["AIWF_STORE_BACKEND"] = "sqlite"
            env["AIWF_STORE_FILE"] = str(case_output / "store.sqlite3")
            started = time.monotonic()
            try:
                proc = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, timeout=args.timeout_sec)
                duration = round(time.monotonic() - started, 3)
                (case_output / "stdout.log").write_text(proc.stdout, encoding="utf-8")
                (case_output / "stderr.log").write_text(proc.stderr, encoding="utf-8")
                run = _extract_json(proc.stdout) if proc.stdout.strip() else {}
                (case_output / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                validation = _run_validation(project, args.validation_timeout_sec)
                (case_output / "validation-result.json").write_text(json.dumps(validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                after = _snapshot(project)
                changed = sorted(set(before) | set(after), key=str.lower)
                changed = [path for path in changed if before.get(path) != after.get(path)]
                expected_missing = [path for path in case["meta"].get("expected_files", []) if not (project / path).exists()]
                run_status = str(run.get("status") or "unknown")
                status = "PASS" if proc.returncode == 0 and run_status == "done" and validation["status"] == "PASS" and not expected_missing else "FAIL"
                item = {
                    "case": label,
                    "status": status,
                    "run_status": run_status,
                    "run_id": run.get("id"),
                    "validation_status": validation["status"],
                    "controller_validation_status": _validation_status(run),
                    "retries": _retry_count(run),
                    "duration_sec": duration,
                    "changed_files": changed,
                    "expected_missing": expected_missing,
                    "error": run.get("error") or proc.stderr[-1000:],
                }
            except subprocess.TimeoutExpired as exc:
                duration = round(time.monotonic() - started, 3)
                (case_output / "stdout.log").write_text(exc.stdout or "", encoding="utf-8")
                (case_output / "stderr.log").write_text(exc.stderr or "", encoding="utf-8")
                item = {"case": label, "status": "FAIL", "run_status": "timeout", "validation_status": "NOT_RUN", "retries": 0, "duration_sec": duration, "changed_files": [], "error": f"timeout after {args.timeout_sec}s"}
            (case_output / "summary.json").write_text(json.dumps(item, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            results.append(item)
            print(f"[{item['status']}] {label} · {item.get('duration_sec', 0)}s · retry={item.get('retries', 0)}")

    passed = sum(1 for item in results if item["status"] in {"PASS", "DRY_RUN"})
    failed = sum(1 for item in results if item["status"] == "FAIL")
    aggregate = {
        "schema": "aiwf.local-real-agent-cases.v1",
        "status": "PASS" if failed == 0 else "FAIL",
        "agent": args.agent,
        "workflow": args.workflow,
        "passed": passed,
        "failed": failed,
        "results": results,
    }
    (output / "summary.json").write_text(json.dumps(aggregate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _write_markdown(output, aggregate)
    print(json.dumps(aggregate, indent=2, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

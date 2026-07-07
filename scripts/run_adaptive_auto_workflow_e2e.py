from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from e2e_log_utils import iter_project_snapshot_files

CASES = [
    ("01-normal-pass", "", False),
    ("02-execute-no-files-retry", "adaptive_no_files_once", False),
    ("03-review-fail-repair", "adaptive_review_fail_once", False),
    ("04-validation-fail-repair", "adaptive_validation_fail_once", True),
]


def wait_for_terminal_run(client: TestClient, run: dict, timeout_sec: float = 45.0) -> dict:
    deadline = time.time() + timeout_sec
    run_id = run["id"]
    while time.time() < deadline:
        response = client.get(f"/api/workflow-runs/{run_id}")
        response.raise_for_status()
        current = response.json()
        if current.get("status") in {"done", "failed", "cancelled", "waiting_input"}:
            return current
        time.sleep(0.2)
    raise TimeoutError(f"run {run_id} did not finish within {timeout_sec}s")


def copy_run_logs(project_dir: Path, run: dict, output_root: Path, label: str) -> dict:
    dest = output_root / label
    dest.mkdir(parents=True, exist_ok=True)
    workspace = Path(run["workspace"])
    if workspace.exists():
        shutil.copytree(workspace, dest / "run-workspace", dirs_exist_ok=True)
    project_snapshot = dest / "project-snapshot"
    project_snapshot.mkdir(parents=True, exist_ok=True)
    for path in iter_project_snapshot_files(project_dir):
        rel = path.relative_to(project_dir)
        target = project_snapshot / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    (dest / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    timeline = "\n".join(f"{item.get('time') or item.get('created_at','')} {item.get('kind','')} {item.get('message','')}" for item in run.get("timeline", []))
    (dest / "timeline.txt").write_text(timeline + "\n", encoding="utf-8")
    steps = [
        {"key": step.get("key"), "status": step.get("status"), "error": step.get("error"), "retry_count": step.get("retry_count") or step.get("retryCount"), "events": step.get("events") or []}
        for step in run.get("steps", [])
    ]
    (dest / "steps.json").write_text(json.dumps(steps, indent=2, ensure_ascii=False), encoding="utf-8")
    trace_path = workspace / ".workflow" / "run-trace.json"
    return json.loads(trace_path.read_text(encoding="utf-8")) if trace_path.exists() else {}


def create_project(root: Path, *, with_validation: bool) -> Path:
    project_dir = root / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "README.md").write_text("# Adaptive Auto Workflow Mock Project\n", encoding="utf-8")
    if with_validation:
        (project_dir / "validation.py").write_text(
            "from workflow_mock_feature import workflow_greeting\n"
            "assert workflow_greeting() == 'hello from controlled workflow'\n"
            "print('external validation ok')\n",
            encoding="utf-8",
        )
    return project_dir


def run_case(client: TestClient, output_root: Path, label: str, *, scenario: str, with_validation: bool) -> dict:
    os.environ["QWEN_MOCK_SCENARIO"] = scenario
    project_dir = create_project(output_root / "projects" / label, with_validation=with_validation)
    session_resp = client.post("/api/sessions", json={"title": f"adaptive e2e {label}", "project_path": str(project_dir)})
    session_resp.raise_for_status()
    session = session_resp.json()
    payload = {
        "workflow_id": "adaptive-auto-workflow",
        "project_path": str(project_dir),
        "requirement": "Create a deterministic Python helper named workflow_greeting and verify it with tests.",
        "test_command": "python -c \"from workflow_mock_feature import workflow_greeting; assert workflow_greeting() == \\\"hello from controlled workflow\\\"\"",
    }
    if with_validation:
        payload["validation_script"] = "validation.py"
    run_resp = client.post(f"/api/sessions/{session['id']}/workflow-runs", json=payload)
    run_resp.raise_for_status()
    run = wait_for_terminal_run(client, run_resp.json())
    trace = copy_run_logs(project_dir, run, output_root, label)
    review_trace = next((step for step in trace.get("steps", []) if step.get("key") == "ai_review"), {})
    effective_path = review_trace.get("effective_prompt_path") or ""
    effective_text = ""
    if effective_path:
        effective_file = Path(run["workspace"]) / effective_path
        if effective_file.exists():
            effective_text = effective_file.read_text(encoding="utf-8")
    return {"case": label, "status": run.get("status"), "error": run.get("error"), "workspace": run.get("workspace"), "ai_review_prompt_had_validation_result": "# Python Gate Result" in effective_text or "Mode: pytest" in effective_text}


def configure_env(output_root: Path) -> None:
    os.environ["QWEN_MOCK"] = "1"
    os.environ["QWEN_USE_SERVE"] = "0"
    os.environ["QWEN_WORKFLOW_SHOW_AGENT_STDOUT"] = "0"
    os.environ["QWEN_WORKFLOW_MOCK_FILE_BLOCK_NORMALIZATION"] = "1"
    os.environ.setdefault("WORKFLOW_TEST_TIMEOUT_SEC", "20")
    os.environ["AIWF_STORE_FILE"] = str(output_root / "store.json")


def run_child(output_root: Path, label: str, scenario: str, with_validation: bool) -> int:
    configure_env(output_root)
    store_dir = output_root / ".stores"
    store_dir.mkdir(parents=True, exist_ok=True)
    os.environ["AIWF_STORE_FILE"] = str(store_dir / f"{label}.json")
    from app.main import app
    result: dict | None = None
    # Write the per-case summary before TestClient shutdown. Some Python/ASGI
    # test environments can hang while draining background tasks after the run is
    # already terminal; the parent runner can still collect complete logs and kill
    # the child safely once this summary exists.
    with TestClient(app) as client:
        result = run_case(client, output_root, label, scenario=scenario, with_validation=with_validation)
        (output_root / label / "case-summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
    return 0 if result and result["status"] == "done" and result["ai_review_prompt_had_validation_result"] else 1


def _parse_output_root(default: str) -> Path:
    parser = argparse.ArgumentParser(description="Run workflow E2E scenarios and export logs.")
    parser.add_argument("output", nargs="?", help="Output directory (legacy positional).")
    parser.add_argument("--output", dest="output_option", help="Output directory.")
    args = parser.parse_args()
    return Path(args.output_option or args.output or default).resolve()


def main() -> int:
    output_root = _parse_output_root("adaptive-auto-workflow-e2e-logs")
    if os.environ.get("AIWF_E2E_CHILD") == "1":
        label = os.environ["AIWF_E2E_LABEL"]
        scenario = os.environ.get("AIWF_E2E_SCENARIO", "")
        with_validation = os.environ.get("AIWF_E2E_WITH_VALIDATION", "0") == "1"
        return run_child(output_root, label, scenario, with_validation)

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    configure_env(output_root)
    from app.main import app
    results: list[dict] = []
    # Run all scenarios in one isolated TestClient. This keeps the E2E runner
    # deterministic and avoids child-process cleanup issues in constrained CI.
    with TestClient(app) as client:
        for label, scenario, with_validation in CASES:
            print(f"running {label}...", flush=True)
            result = run_case(client, output_root, label, scenario=scenario, with_validation=with_validation)
            print(f"done {label}: {result.get('status')}", flush=True)
            (output_root / label / "case-summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            results.append(result)
    all_done = all(item["status"] == "done" for item in results)
    validation_seen = all(item.get("ai_review_prompt_had_validation_result") for item in results)
    summary = {"status": "PASS" if all_done and validation_seen else "FAIL", "results": results}
    (output_root / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

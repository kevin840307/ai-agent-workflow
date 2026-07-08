from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from e2e_log_utils import copy_pruned_tree, iter_project_snapshot_files

SMOKE_CASES = {
    "sort": {
        "requirement": "Create sort_utils.py with bubble_sort(data) returning a sorted list without mutating the input. Add focused tests when useful.",
        "validation": "from pathlib import Path\nimport importlib.util\ntarget = Path('sort_utils.py')\nassert target.exists(), 'sort_utils.py is missing'\nspec = importlib.util.spec_from_file_location('sort_utils', target)\nmod = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(mod)\nassert mod.bubble_sort([3, 1, 2]) == [1, 2, 3]\nassert mod.bubble_sort([2, 2, -1]) == [-1, 2, 2]\nprint('validation ok')\n",
    },
    "config-loader": {
        "requirement": "Create config_loader.py with load_config(path) that loads a JSON file and returns a dictionary. Add focused tests when useful.",
        "validation": "from pathlib import Path\nimport json\nimport importlib.util\nPath('sample.json').write_text(json.dumps({'a': 1}), encoding='utf-8')\nspec = importlib.util.spec_from_file_location('config_loader', Path('config_loader.py'))\nassert Path('config_loader.py').exists(), 'config_loader.py is missing'\nmod = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(mod)\nassert mod.load_config('sample.json') == {'a': 1}\nprint('validation ok')\n",
    },
    "readme": {
        "requirement": "Update README.md with a short Usage section and keep the project simple. No production code is required.",
        "validation": "from pathlib import Path\ntext = Path('README.md').read_text(encoding='utf-8')\nassert 'Usage' in text or 'usage' in text.lower(), 'README Usage section missing'\nprint('validation ok')\n",
    },
}


def wait_for_terminal_run(client: TestClient, run: dict, timeout_sec: float) -> dict:
    deadline = time.time() + timeout_sec
    run_id = run["id"]
    while time.time() < deadline:
        resp = client.get(f"/api/workflow-runs/{run_id}")
        resp.raise_for_status()
        current = resp.json()
        if current.get("status") in {"done", "failed", "cancelled", "waiting_input"}:
            return current
        time.sleep(0.5)
    raise TimeoutError(f"run {run_id} did not finish within {timeout_sec}s")


def create_fixture_project(root: Path, case: str) -> Path:
    project = root / f"{case}-project"
    if project.exists():
        shutil.rmtree(project)
    project.mkdir(parents=True)
    (project / "README.md").write_text(f"# Real Agent Smoke {case}\n", encoding="utf-8")
    spec = SMOKE_CASES[case]
    (project / "validation.py").write_text(spec["validation"], encoding="utf-8")
    return project


def copy_logs(project: Path, run: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "run.json").write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    workspace = Path(run.get("workspace") or "")
    if workspace.exists():
        (out / "run-workspace.txt").write_text(str(workspace), encoding="utf-8")
    snap = out / "project-snapshot"
    snap.mkdir(exist_ok=True)
    for path in iter_project_snapshot_files(project):
        rel = path.relative_to(project)
        target = snap / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def self_prompt_review(payload: dict) -> dict:
    """Local smoke self-check: validates the prompt we are about to send before involving a real agent.

    This is intentionally deterministic. It approximates the manual step of asking an assistant:
    "Does this smoke prompt actually test a real agent and stay inside the fixture project?"
    """
    prompt = str(payload.get("requirement") or "")
    problems: list[str] = []
    if len(prompt.strip()) < 20:
        problems.append("requirement is too short")
    if any(marker in prompt.lower() for marker in ["mkdir ", "echo ", ">>", "file:", "end_file"]):
        problems.append("requirement looks like shell/file-block output instead of a human CLI prompt")
    if not payload.get("validation_script"):
        problems.append("validation_script is missing")
    if not Path(payload.get("project_path") or "").exists():
        problems.append("project_path does not exist")
    return {
        "status": "PASS" if not problems else "FAIL",
        "summary": "self-prompt smoke payload is ready" if not problems else "self-prompt smoke payload has issues",
        "problems": problems,
        "prompt_to_review": (
            "Review this real-agent smoke request before running Qwen/OpenCode. "
            "Confirm it is a concise human CLI instruction, includes validation.py, and only targets the fixture project.\n\n"
            f"Workflow: {payload.get('workflow_id')}\nAgent: {payload.get('agent')}\nRequirement: {prompt}\n"
        ),
    }


def write_markdown_report(output: Path, summary: dict) -> None:
    lines = [
        "# Real Agent Smoke Report",
        "",
        f"- Status: {summary.get('status')}",
        f"- Workflow: {summary.get('workflow')}",
        f"- Agent: {summary.get('agent')}",
        f"- Case: {summary.get('case')}",
        f"- Run ID: {summary.get('run_id', '-')}",
        f"- Error: {summary.get('error') or '-'}",
        "",
        "## Self-prompt Review",
    ]
    review = summary.get("self_prompt_review") or summary.get("review") or {}
    lines.append(f"- Review Status: {review.get('status', '-')}")
    for item in review.get("problems") or []:
        lines.append(f"- Problem: {item}")
    output.mkdir(parents=True, exist_ok=True)
    (output / "real-agent-smoke-report.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a manually-triggered real Qwen/OpenCode smoke workflow against tiny fixture projects.")
    parser.add_argument("--agent", choices=["qwen", "opencode"], default="qwen")
    parser.add_argument("--workflow", choices=["adaptive-auto-workflow", "general-auto-development"], default="adaptive-auto-workflow")
    parser.add_argument("--case", choices=sorted(SMOKE_CASES), default="sort")
    parser.add_argument("--output", default="real-agent-smoke-logs")
    parser.add_argument("--list-cases", action="store_true", help="List available real-agent smoke cases and exit.")
    parser.add_argument("--timeout-sec", type=float, default=180)
    parser.add_argument("--allow-mock", action="store_true", help="Allow QWEN_MOCK=1 for local dry-runs. By default mock mode is rejected.")
    parser.add_argument("--dry-run", action="store_true", help="Only create the fixture and print the payload; do not start a workflow run.")
    parser.add_argument("--self-prompt-test", action="store_true", help="Validate and print the smoke prompt first, before starting a real agent run.")
    args = parser.parse_args()

    if args.list_cases:
        print(json.dumps({"cases": sorted(SMOKE_CASES)}, indent=2, ensure_ascii=False))
        return 0

    if os.environ.get("QWEN_MOCK") == "1" and not args.allow_mock and not args.dry_run and not args.self_prompt_test:
        print("Refusing to run real-agent smoke while QWEN_MOCK=1. Use --allow-mock for dry-run only.", file=sys.stderr)
        return 2
    os.environ.setdefault("QWEN_USE_SERVE", "0")
    os.environ["AIWF_STORE_FILE"] = str(Path(args.output).resolve() / "store.json")

    output = Path(args.output).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    project = create_fixture_project(output / "fixture", args.case)
    payload = {
        "workflow_id": args.workflow,
        "project_path": str(project),
        "requirement": SMOKE_CASES[args.case]["requirement"],
        "validation_script": "validation.py",
        "test_command": "python validation.py",
        "agent": args.agent,
        "runProfile": "small",
    }
    review = self_prompt_review(payload)
    (output / "self-prompt-review.json").write_text(json.dumps(review, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.self_prompt_test:
        summary = {"status": review["status"], "mode": "SELF_PROMPT_TEST", "workflow": args.workflow, "agent": args.agent, "case": args.case, "payload": payload, "review": review}
        (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        write_markdown_report(output, summary)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0 if review["status"] == "PASS" else 1
    if args.dry_run:
        summary = {"status": "DRY_RUN", "workflow": args.workflow, "agent": args.agent, "case": args.case, "project_path": str(project), "payload": payload, "self_prompt_review": review}
        (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        write_markdown_report(output, summary)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    from app.main import app

    with TestClient(app) as client:
        session = client.post("/api/sessions", json={"title": f"real {args.agent} smoke", "project_path": str(project)}).json()
        resp = client.post(f"/api/sessions/{session['id']}/workflow-runs", json=payload)
        resp.raise_for_status()
        run = wait_for_terminal_run(client, resp.json(), args.timeout_sec)
    copy_logs(project, run, output)
    summary = {"status": "PASS" if run.get("status") == "done" else "FAIL", "workflow": args.workflow, "agent": args.agent, "case": args.case, "run_id": run.get("id"), "error": run.get("error"), "output": str(output), "self_prompt_review": review}
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown_report(output, summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient


def _wait(client: TestClient, run_id: str, timeout_sec: float) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        run = client.get(f"/api/workflow-runs/{run_id}").json()
        if run.get("status") in {"done", "failed", "cancelled", "waiting_input"}:
            return run
        time.sleep(0.2)
    raise TimeoutError(f"case run {run_id} did not finish within {timeout_sec}s")


def _load_case(case_dir: Path) -> dict:
    requirement = (case_dir / "requirement.md").read_text(encoding="utf-8")
    expected = json.loads((case_dir / "expected_behavior.json").read_text(encoding="utf-8"))
    return {"case": case_dir.name, "requirement": requirement, "expected": expected}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run reusable workflow case fixtures with the mock agent.")
    parser.add_argument("--cases-dir", default="tests/workflow_cases")
    parser.add_argument("--output", default="workflow-case-library-logs")
    parser.add_argument("--timeout-sec", type=float, default=90)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true", help="Actually run every case with the mock workflow runner. Without this, the script lists and validates the case library only.")
    args = parser.parse_args()

    cases_root = Path(args.cases_dir)
    cases = [_load_case(path) for path in sorted(cases_root.iterdir()) if (path / "requirement.md").exists()]
    output = Path(args.output).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    (output / "cases.json").write_text(json.dumps(cases, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.dry_run or not args.execute:
        mode = "DRY_RUN" if args.dry_run else "CASE_LIBRARY_READY"
        print(json.dumps({"status": mode, "case_count": len(cases), "output": str(output), "hint": "Use --execute to run every case with mock workflows."}, indent=2))
        return 0

    import os
    os.environ["QWEN_MOCK"] = "1"
    os.environ.setdefault("QWEN_USE_SERVE", "0")
    os.environ["AIWF_STORE_FILE"] = str(output / "store.json")
    from app.main import app

    results = []
    with TestClient(app) as client:
        for case in cases:
            project = output / "projects" / case["case"]
            project.mkdir(parents=True, exist_ok=True)
            (project / "README.md").write_text(f"# {case['case']}\n", encoding="utf-8")
            validation_src = cases_root / case["case"] / "validation.py"
            validation_script = "validation.py"
            if validation_src.exists():
                shutil.copy2(validation_src, project / "validation.py")
            else:
                (project / "validation.py").write_text("print(\"validation ok\")\n", encoding="utf-8")
            session = client.post("/api/sessions", json={"title": case["case"], "project_path": str(project)}).json()
            payload = {
                "workflow_id": case["expected"].get("workflow") or "adaptive-auto-workflow",
                "project_path": str(project),
                "requirement": case["requirement"],
                "validation_script": validation_script or case["expected"].get("validation_script"),
                "runProfile": "small"
            }
            run = client.post(f"/api/sessions/{session['id']}/workflow-runs", json={k: v for k, v in payload.items() if v}).json()
            done = _wait(client, run["id"], args.timeout_sec)
            results.append({"case": case["case"], "status": done.get("status"), "run_id": done.get("id"), "error": done.get("error")})
    summary = {"status": "PASS" if all(item["status"] == "done" for item in results) else "FAIL", "results": results}
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

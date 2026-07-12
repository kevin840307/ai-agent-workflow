#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.paths import utc_now, write_text  # noqa: E402
from app.workflow_runtime.event_log import append_event  # noqa: E402
from app.workflow_runtime.run_artifacts import write_standard_run_artifacts  # noqa: E402
from app.runtime_modules.run_owner import current_run_owner  # noqa: E402
from app.workflow_runtime.run_lifecycle import (  # noqa: E402
    cleanup_stale_project_lock,
    mark_interrupted_store_runs,
    write_project_lock,
)
from app.workflow_runtime.run_consistency import check_store_consistency  # noqa: E402


def _fake_run(project: Path, run_id: str, status: str = "running") -> dict:
    workspace = project / ".ai-workflow" / "runs" / "session-crash" / f"run-{run_id}"
    (workspace / ".workflow").mkdir(parents=True, exist_ok=True)
    run = {
        "id": run_id,
        "session_id": "session-crash",
        "workflow_id": "crash-recovery-test",
        "status": status,
        "project_path": str(project),
        "workspace": str(workspace),
        "run_owner": current_run_owner(),
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "steps": [{"key": "build", "title": "Build", "status": "running", "retry_count": 0}],
        "artifacts": [],
        "timeline": [],
    }
    write_text(workspace / ".workflow" / "state.json", json.dumps(run, indent=2, ensure_ascii=False))
    write_text(workspace / ".workflow" / "events.jsonl", json.dumps({"type": "run.started", "run_id": run_id}) + "\n")
    return run


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate interrupted-run recovery and stale-lock cleanup.")
    parser.add_argument("--output", default=str(ROOT / "reports" / "crash-recovery-test"))
    args = parser.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="aiwf-crash-recovery-"))
    try:
        project = tmp / "project"
        project.mkdir()
        run = _fake_run(project, "crash-run")
        data = {"runs": [run], "sessions": [], "messages": [], "workflow_configs": []}
        write_project_lock(run)
        changed = mark_interrupted_store_runs(data)
        cleanup = cleanup_stale_project_lock(project, data)
        for item in changed:
            workspace = Path(item["workspace"])
            write_text(workspace / ".workflow" / "state.json", json.dumps(item, indent=2, ensure_ascii=False))
            append_event(item, "run.failed", message="Crash recovery marked run interrupted.", status="failed", error_code="INTERRUPTED")
            write_standard_run_artifacts(item, workspace)
        consistency = check_store_consistency(data)
        report = {
            "schema": "aiwf.crash-recovery-test.v1",
            "status": "PASS" if changed and cleanup.get("removed") and consistency.get("status") == "PASS" else "FAIL",
            "changed_count": len(changed),
            "cleanup": cleanup,
            "consistency": consistency,
        }
        out = Path(args.output).expanduser().resolve()
        out.mkdir(parents=True, exist_ok=True)
        (out / "crash-recovery-test-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["status"] == "PASS" else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

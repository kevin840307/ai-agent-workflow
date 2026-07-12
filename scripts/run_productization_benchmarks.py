#!/usr/bin/env python3
"""Run the fixed V9 benchmark catalog against a live controller.

Safe defaults:
- without --execute it only prints/writes the catalog;
- --execute requires an existing Project Path and session or creates an isolated
  subdirectory per case;
- --real is required when the controller is not in mock mode.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path

CASES = {
    "BENCH-001": "Create a small Python utility module with one function and focused tests.",
    "BENCH-002": "Add a multi-file Python feature with a service module, public API, and tests.",
    "BENCH-003": "Repair the intentionally failing test without changing unrelated behavior.",
    "BENCH-004": "Refactor the sample module while preserving its public API and passing all regression tests.",
    "BENCH-005": "Complete the task and recover safely if the agent process times out.",
    "BENCH-006": "Complete the task while exercising lost-session recovery.",
    "BENCH-007": "Complete the task while exercising context handoff to a fresh session.",
    "BENCH-008": "Complete the task and verify checkpoint recovery after controller restart.",
    "BENCH-009": "Verify that only one write Run can own this Project Path.",
    "BENCH-010": "Create only the requested function and tests; report and remove unrelated scope expansion.",
    "BENCH-011": "Repair the implementation after the required external validation fails, then make the final gate pass.",
    "BENCH-012": "Recover from repeated no-file-change attempts by rotating to a fresh session without exceeding the recovery budget.",
    "BENCH-013": "Make a focused change in a large legacy project using the incremental project index and finish with the full validation gate.",
    "BENCH-014": "Detect and execute the appropriate build and test plan for a Java, .NET, Node, or Python project without hardcoded project commands.",
}


def request(base: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--session")
    parser.add_argument("--workflow", default="general-auto-development")
    parser.add_argument("--agent", default="qwen")
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--poll-sec", type=float, default=2.0)
    parser.add_argument("--timeout-sec", type=int, default=3600)
    parser.add_argument("--output", type=Path, default=Path("reports/v9-benchmark-results.json"))
    args = parser.parse_args()

    selected = args.cases or list(CASES)
    unknown = [item for item in selected if item not in CASES]
    if unknown:
        parser.error(f"Unknown benchmark cases: {', '.join(unknown)}")
    if not args.execute:
        payload = {"execute": False, "cases": [{"id": case, "requirement": CASES[case]} for case in selected]}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps(payload, indent=2))
        return 0
    if not args.project:
        parser.error("--project is required with --execute")
    project = args.project.expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    setup = request(args.base_url, "GET", f"/api/setup/status?projectPath={urllib.parse.quote(str(project))}")
    if not args.real and not bool(setup.get("mock_mode")):
        parser.error("Use --real to execute against a non-mock controller")
    if not setup.get("ready"):
        blocking = [item.get("title") for item in setup.get("steps", []) if item.get("status") == "blocked"]
        parser.error(f"Controller setup is not ready: {', '.join(blocking) or 'unknown blocking check'}")
    session_id = args.session
    if not session_id:
        session = request(args.base_url, "POST", "/api/sessions", {"project_path": str(project), "title": "V9 benchmark"})
        session_id = session["id"]

    results = []
    for case in selected:
        case_project = project / case.lower()
        case_project.mkdir(parents=True, exist_ok=True)
        # Each case uses its own session/project to avoid cross-case session and
        # filesystem contamination.
        session = request(args.base_url, "POST", "/api/sessions", {"project_path": str(case_project), "title": case})
        run = request(
            args.base_url,
            "POST",
            f"/api/sessions/{session['id']}/workflow-runs",
            {
                "requirement": CASES[case],
                "workflow_id": args.workflow,
                "agent": args.agent,
                "benchmarkId": case,
                "runProfile": "small" if case == "BENCH-001" else "normal",
            },
        )
        deadline = time.monotonic() + args.timeout_sec
        while run.get("status") in {"queued", "running", "waiting_input", "cancelling"} and time.monotonic() < deadline:
            time.sleep(args.poll_sec)
            run = request(args.base_url, "GET", f"/api/workflow-runs/{run['id']}")
        overview = request(args.base_url, "GET", f"/api/workflow-runs/{run['id']}/overview")
        results.append({"case": case, "run_id": run["id"], "status": run.get("status"), "overview": overview})
        print(f"{case}: {run.get('status')}")

    payload = {"execute": True, "base_url": args.base_url, "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if all(item["status"] == "done" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
